#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Shared client library for venator GUIs (TUI + Qt).

Architecture (decided in Phase 5 planning):
  - State queries: read /sys/class/venator/keyboard0/ directly. Always
    fast, no privilege issue (user is in the venator group via the
    udev rule).
  - State mutations: shell out to the `venator` CLI. Keeps the
    CLI canonical so GUIs don't need to reimplement profile auto-save,
    background keepalive, animator detachment, mode-name -> EFF byte
    mapping, etc.

  Frontends (TUI in tui.py, Qt6 in qt.py later) import the classes
  defined here so they stay in sync.

KeyboardLayout encapsulates the (col, row) -> cell-index mapping plus
the optional name-from-keymap-json lookup. Cell arithmetic on PH16-71 is
regular: `cell = col * 6 + row_from_bottom`, 22 logical columns.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Iterable

SYSFS_ROOT = Path("/sys/class/venator")
SHARE_DIRS = [
    Path("/usr/local/share/venator"),
    Path("/usr/share/venator"),
]


def _real_home() -> Path:
    """Honour SUDO_USER so per-user data lives in the invoking user's
    home, not /root, when this is somehow imported under sudo."""
    su = os.environ.get("SUDO_USER")
    if su and os.geteuid() == 0:
        try:
            import pwd
            return Path(pwd.getpwnam(su).pw_dir)
        except (KeyError, ImportError):
            pass
    return Path(os.path.expanduser("~"))


USER_CONFIG = _real_home() / ".config" / "venator"


# ----------------------------------------------------------------------- client

class PredatorSenseClient:
    """Wraps the venator CLI + direct sysfs reads."""

    def __init__(self, cli_path: str | None = None):
        if not SYSFS_ROOT.exists():
            raise RuntimeError(
                f"{SYSFS_ROOT} not found. Is the venator kernel module loaded?"
            )
        # Phase 6 added a sibling `battery0` device under the same class.
        # Pick the keyboard explicitly so the GUI/TUI doesn't end up
        # reading /sys/class/venator/battery0/mode.
        kbds = sorted(p for p in SYSFS_ROOT.iterdir()
                      if p.is_dir() and p.name.startswith("keyboard"))
        if not kbds:
            # Fallback: any dir that has the LED `mode` attr.
            kbds = [p for p in sorted(SYSFS_ROOT.iterdir())
                    if p.is_dir() and (p / "mode").exists()]
        if not kbds:
            raise RuntimeError(f"No keyboard device under {SYSFS_ROOT}.")
        self.dev = kbds[0]
        # Battery device (optional — only present when our WMI half
        # bound). None on stock acer-wmi-battery boards too; the
        # threshold attribute may also appear under /sys/class/power_supply.
        bats = [p for p in sorted(SYSFS_ROOT.iterdir())
                if p.is_dir() and p.name.startswith("battery")]
        self.battery_dev: Path | None = bats[0] if bats else None

        if cli_path is None:
            for candidate in ("/usr/local/bin/venator",
                              "/usr/bin/venator",
                              "venator"):
                if candidate == "venator" or Path(candidate).exists():
                    cli_path = candidate
                    break
        self.cli_path = cli_path or "venator"
        self._lock = threading.Lock()

    # ---- sysfs reads (always available, no privilege required)

    def _read_text(self, attr: str, default: str = "") -> str:
        p = self.dev / attr
        try:
            return p.read_text().strip()
        except OSError:
            return default

    def _read_bin(self, attr: str) -> bytes:
        p = self.dev / attr
        try:
            return p.read_bytes()
        except OSError:
            return b""

    def info(self) -> dict[str, str]:
        out: dict[str, str] = {}
        info_dir = self.dev / "info"
        if info_dir.is_dir():
            for f in info_dir.iterdir():
                if f.is_file():
                    try:
                        out[f.name] = f.read_text().strip()
                    except OSError:
                        pass
        return out

    def get_mode(self) -> str:        return self._read_text("mode")
    def get_color(self) -> str:       return self._read_text("color")
    def get_brightness(self) -> int:
        s = self._read_text("brightness", "0")
        try:    return int(s)
        except: return 0
    def get_effect_id(self) -> int:
        s = self._read_text("effect_id", "0")
        try:    return int(s)
        except: return 0
    def get_frame(self) -> bytes:
        # Driver returns 384 bytes (128 * 3 RGB).
        return self._read_bin("frame")

    def available_modes(self) -> list[str]:
        return self.info().get("available_modes", "").split()

    def num_cells(self) -> int:
        try:    return int(self.info().get("num_cells", "128"))
        except: return 128

    def device_name(self) -> str:
        return self.info().get("dev_name", "PH16-71")

    # ---- CLI shell-outs (state mutations)

    def _run(self, *args: str, timeout: float = 15.0) -> subprocess.CompletedProcess:
        with self._lock:
            return subprocess.run(
                [self.cli_path, *args],
                capture_output=True, text=True, timeout=timeout, check=False,
            )

    def rgb_off(self) -> subprocess.CompletedProcess:
        return self._run("rgb", "off")

    def rgb_static(self, hex_color: str, *, brightness: int | None = None,
                   timeout: int = 0) -> subprocess.CompletedProcess:
        args = ["rgb", "static", hex_color, "--timeout", str(timeout)]
        if brightness is not None:
            args += ["--brightness", str(brightness)]
        return self._run(*args)

    def rgb_effect(self, name: str, *, hex_color: str | None = None,
                   brightness: int | None = None, timeout: int = 0
                   ) -> subprocess.CompletedProcess:
        args = ["rgb", "effect", name, "--timeout", str(timeout)]
        if hex_color is not None:
            args += ["--color", hex_color]
        if brightness is not None:
            args += ["--brightness", str(brightness)]
        return self._run(*args)

    def rgb_fill(self, hex_color: str, *, brightness: int | None = None,
                 timeout: int = 0) -> subprocess.CompletedProcess:
        args = ["rgb", "fill", hex_color, "--timeout", str(timeout)]
        if brightness is not None:
            args += ["--brightness", str(brightness)]
        return self._run(*args)

    def rgb_design(self, name: str, *, brightness: int | None = None,
                   timeout: int = 0) -> subprocess.CompletedProcess:
        args = ["rgb", "design", name, "--timeout", str(timeout)]
        if brightness is not None:
            args += ["--brightness", str(brightness)]
        return self._run(*args)

    def rgb_animate(self, name: str, *, brightness: int | None = None,
                    timeout: int = 0) -> subprocess.CompletedProcess:
        args = ["rgb", "animate", name, "--timeout", str(timeout)]
        if brightness is not None:
            args += ["--brightness", str(brightness)]
        return self._run(*args)

    def rgb_key(self, key_name: str, hex_color: str, *,
                brightness: int | None = None, timeout: int = 0
                ) -> subprocess.CompletedProcess:
        args = ["rgb", "key", key_name, hex_color, "--timeout", str(timeout)]
        if brightness is not None:
            args += ["--brightness", str(brightness)]
        return self._run(*args)

    def rgb_keys(self, key_names: Iterable[str], hex_color: str, *,
                 brightness: int | None = None, timeout: int = 0
                 ) -> subprocess.CompletedProcess:
        joined = ",".join(key_names)
        args = ["rgb", "keys", joined, hex_color, "--timeout", str(timeout)]
        if brightness is not None:
            args += ["--brightness", str(brightness)]
        return self._run(*args)

    def rgb_perkey(self, frame: bytes, *, brightness: int | None = None,
                   timeout: int = 0) -> subprocess.CompletedProcess:
        """Push a 384-byte (128 cells * RGB) per-key frame buffer."""
        import tempfile
        with tempfile.NamedTemporaryFile(
                delete=False, dir="/tmp", prefix="ps-frame-") as f:
            f.write(frame)
            tmp = f.name
        try:
            args = ["rgb", "perkey", tmp, "--timeout", str(timeout)]
            if brightness is not None:
                args += ["--brightness", str(brightness)]
            return self._run(*args)
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    # ---- profiles

    def profile_save(self, name: str) -> subprocess.CompletedProcess:
        return self._run("profile", "save", name)

    def profile_load(self, name: str) -> subprocess.CompletedProcess:
        return self._run("profile", "load", name)

    def profile_delete(self, name: str) -> subprocess.CompletedProcess:
        return self._run("profile", "delete", name)

    def profile_list(self) -> list[str]:
        r = self._run("profile", "list")
        if r.returncode != 0:
            return []
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

    # ----------- power / thermal / battery (read sysfs direct;
    #             mutations shell out so PPD interactions etc are
    #             handled by the canonical CLI logic)

    def get_power_profile(self) -> str | None:
        p = Path("/sys/firmware/acpi/platform_profile")
        try:
            return p.read_text().strip()
        except OSError:
            return None

    def get_power_profile_choices(self) -> list[str]:
        p = Path("/sys/firmware/acpi/platform_profile_choices")
        try:
            return p.read_text().split()
        except OSError:
            return []

    def set_power_profile(self, name: str) -> subprocess.CompletedProcess:
        return self._run("power", name)

    def detach_ppd(self) -> subprocess.CompletedProcess:
        return self._run("power", "--detach-ppd")

    def attach_ppd(self) -> subprocess.CompletedProcess:
        return self._run("power", "--attach-ppd")

    # ----------- per-source power policy (AC vs battery)

    def on_ac_power(self) -> bool | None:
        """True on AC, False on battery, None if no adapter is detected.
        Read straight from sysfs to match the CLI's _on_ac_power().
        """
        import glob
        found = False
        for d in sorted(glob.glob("/sys/class/power_supply/*")):
            dp = Path(d)
            try:
                if (dp / "type").read_text().strip() == "Battery":
                    continue
            except OSError:
                continue
            online = dp / "online"
            if not online.exists():
                continue
            try:
                val = online.read_text().strip()
            except OSError:
                continue
            found = True
            if val == "1":
                return True
        return False if found else None

    def get_power_policy(self) -> dict:
        """Read ~/.config/venator/power-policy.json directly.
        Returns {"ac": <raw|None>, "battery": <raw|None>}.
        """
        path = _real_home() / ".config" / "venator" / "power-policy.json"
        if not path.exists():
            return {"ac": None, "battery": None}
        try:
            d = json.loads(path.read_text())
            if not isinstance(d, dict):
                return {"ac": None, "battery": None}
            return {"ac": d.get("ac"), "battery": d.get("battery")}
        except (OSError, ValueError):
            return {"ac": None, "battery": None}

    def set_power_policy(self, slot: str, profile: str,
                         advanced: bool = False) -> subprocess.CompletedProcess:
        """slot is 'ac' or 'battery'. --advanced lets battery take the
        high-power profiles (the CLI rejects them otherwise)."""
        args = ["power-policy", slot, profile]
        if slot == "battery" and advanced:
            args.append("--advanced")
        return self._run(*args)

    def _acer_hwmon(self) -> Path | None:
        import glob
        for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            try:
                if Path(h, "name").read_text().strip() == "acer":
                    return Path(h)
            except OSError:
                pass
        return None

    def get_fans(self) -> dict[int, int]:
        """Return {1: rpm, 2: rpm} from the acer hwmon, missing entries
        elided. RPM 0 means the fan is stopped (idle profile, AC off,
        etc.) — *not* missing."""
        hwm = self._acer_hwmon()
        out: dict[int, int] = {}
        if hwm is None:
            return out
        for i in (1, 2, 3, 4):
            try:
                v = (hwm / f"fan{i}_input").read_text().strip()
                out[i] = int(v)
            except (OSError, ValueError):
                pass
        return out

    def get_temps(self) -> dict[str, int]:
        """Return labelled °C readings from across hwmon devices.
        Keys: "cpu" (acer/temp1), "gpu" (acer/temp2), "chassis"
        (acer/temp3), "cpu_pkg" (coretemp/k10temp temp1), "nvme".
        Missing or zero entries are omitted."""
        import glob
        out: dict[str, int] = {}
        hwm = self._acer_hwmon()
        if hwm is not None:
            mapping = {1: "cpu", 2: "gpu", 3: "chassis"}
            for i, lbl in mapping.items():
                try:
                    v = int((hwm / f"temp{i}_input").read_text().strip())
                except (OSError, ValueError):
                    continue
                if v != 0:                  # GPU often 0 in D3cold
                    out[lbl] = v // 1000
        for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            try:
                name = Path(h, "name").read_text().strip()
            except OSError:
                continue
            if name in ("coretemp", "k10temp"):
                try:
                    out["cpu_pkg"] = int(Path(h, "temp1_input").read_text().strip()) // 1000
                except (OSError, ValueError):
                    pass
            elif name == "nvme":
                try:
                    out["nvme"] = int(Path(h, "temp1_input").read_text().strip()) // 1000
                except (OSError, ValueError):
                    pass
        return out

    def battery_attr_path(self, attr: str) -> Path | None:
        """Find the canonical path for a battery attribute.

        Prefers /sys/class/venator/battery0/ (our own kernel module),
        falls back to /sys/class/power_supply/BAT*/ for boards in
        mainline acer_wmi_battery's quirk list."""
        if self.battery_dev is not None:
            p = self.battery_dev / attr
            if p.exists():
                return p
        import glob
        for b in sorted(glob.glob("/sys/class/power_supply/BAT*")):
            p = Path(b, attr)
            if p.exists():
                return p
        return None

    def get_battery_info(self) -> dict:
        """Snapshot of battery state. Always returns the dict (with
        whatever attrs were readable) so callers can render a partial
        view even on unusual hardware."""
        info: dict = {}
        import glob
        bats = sorted(glob.glob("/sys/class/power_supply/BAT*"))
        if bats:
            info["device"] = bats[0]
            for k in ("manufacturer", "model_name", "technology",
                      "status", "capacity",
                      "voltage_now", "current_now",
                      "charge_full", "charge_full_design", "charge_now"):
                try:
                    info[k] = Path(bats[0], k).read_text().strip()
                except OSError:
                    pass
        # Our own /sys/class/venator/battery0/* (RW from the venator group):
        for k in ("health_mode", "calibration_mode",
                  "charge_control_end_threshold"):
            p = self.battery_attr_path(k)
            if p is not None:
                try:
                    info[k] = p.read_text().strip()
                except OSError:
                    pass
        return info

    def get_health_mode(self) -> int | None:
        p = self.battery_attr_path("health_mode")
        if p is None:
            return None
        try:
            return int(p.read_text().strip())
        except (OSError, ValueError):
            return None

    def set_health_mode(self, enable: bool) -> subprocess.CompletedProcess:
        return self._run("battery", "limit", "on" if enable else "off")

    def get_calibration_mode(self) -> int | None:
        p = self.battery_attr_path("calibration_mode")
        if p is None:
            return None
        try:
            return int(p.read_text().strip())
        except (OSError, ValueError):
            return None

    def set_calibration_mode(self, enable: bool) -> subprocess.CompletedProcess:
        """Toggle the firmware's one-shot calibration cycle. There's
        no `battery calibration` CLI subcommand yet; write the sysfs
        attr directly (works for users in the venator group)."""
        p = self.battery_attr_path("calibration_mode")
        if p is None:
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="",
                stderr="no calibration_mode attr; kernel module loaded?")
        try:
            p.write_text("1" if enable else "0")
        except (PermissionError, OSError) as e:
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=str(e))
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="")

    # ---- lightbar (rear EC RGB strip)

    LIGHTBAR_DIR = Path("/sys/class/venator/lightbar0")
    LIGHTBAR_MODES = ("off", "breathing", "neon", "rainbow",
                      "wave", "ripple", "scanner", "strobe")

    def lightbar_present(self) -> bool:
        return self.LIGHTBAR_DIR.exists()

    def get_lightbar(self) -> dict:
        """Read the kernel's cached lightbar state."""
        out = {}
        for attr in ("mode", "brightness", "speed", "direction", "color"):
            p = self.LIGHTBAR_DIR / attr
            if p.exists():
                try:
                    out[attr] = p.read_text().strip()
                except OSError:
                    pass
        return out

    def set_lightbar(self, *, mode: str | None = None,
                     hex_color: str | None = None,
                     brightness: int | None = None,
                     speed: int | None = None
                     ) -> subprocess.CompletedProcess:
        """Atomic lightbar update via `venator lightbar set`.

        Any field that's None is left at its current value.
        """
        args: list[str] = ["lightbar", "set"]
        if mode is not None:
            args += ["--mode", mode]
        if hex_color is not None:
            args += ["--color", hex_color.lstrip("#")]
        if brightness is not None:
            args += ["--brightness", str(int(brightness))]
        if speed is not None:
            args += ["--speed", str(int(speed))]
        return self._run(*args)

    def lightbar_off(self) -> subprocess.CompletedProcess:
        return self._run("lightbar", "off")

    # ---- animations + designs catalogue (read filesystem, no CLI)

    def list_animations(self) -> dict[str, Path]:
        return _list_share_dir("animations")

    def list_designs(self) -> dict[str, Path]:
        return _list_share_dir("designs")


def _list_share_dir(kind: str) -> dict[str, Path]:
    """{name: path}; user-installed overrides shipped by name."""
    out: dict[str, Path] = {}
    for d in SHARE_DIRS:
        p = d / kind
        if not p.is_dir():
            continue
        for f in sorted(p.iterdir()):
            if f.suffix in (".py", ".json") and not f.stem.startswith("_") and f.stem != "README":
                out[f.stem] = f
    user = USER_CONFIG / kind
    if user.is_dir():
        for f in sorted(user.iterdir()):
            if f.suffix in (".py", ".json") and not f.stem.startswith("_") and f.stem != "README":
                out[f.stem] = f
    return out


# ---------------------------------------------------------------- KeyboardLayout

class KeyboardLayout:
    """Spatial layout of the 128-cell keyboard matrix.

    The matrix is regular: `cell = col * ROWS + row_from_bottom` with
    ROWS = 6 (function-row at the top is row index 0 here for ease of
    rendering; the underlying cell-index encoding has row 5 at the
    top -- we flip).
    """
    ROWS = 6

    def __init__(self, keymap_path: Path | None = None):
        if keymap_path is None:
            keymap_path = _find_default_keymap()
        if keymap_path and keymap_path.exists():
            data = json.loads(keymap_path.read_text())
        else:
            data = {"num_cells": 128, "keys": {}}
        self.num_cells: int = int(data.get("num_cells", 128))
        self.keys: dict[str, int] = dict(data.get("keys", {}))
        # cell_idx -> human-readable key name
        self.cell_to_name: dict[int, str] = {int(v): k for k, v in self.keys.items()}
        self.num_cols: int = (self.num_cells + self.ROWS - 1) // self.ROWS

    def cell_of(self, col: int, row: int) -> int | None:
        """row 0 = top of keyboard (Esc, F-keys), row ROWS-1 = bottom
        (Ctrl, Fn, …). Returns None for out-of-range positions."""
        if not (0 <= col < self.num_cols and 0 <= row < self.ROWS):
            return None
        row_from_bottom = (self.ROWS - 1) - row
        cell = col * self.ROWS + row_from_bottom
        if 0 <= cell < self.num_cells:
            return cell
        return None

    def name_at(self, col: int, row: int) -> str | None:
        cell = self.cell_of(col, row)
        if cell is None:
            return None
        return self.cell_to_name.get(cell)

    def grid(self):
        """Yield (col, row, cell_idx, name|None) for every grid position."""
        for col in range(self.num_cols):
            for row in range(self.ROWS):
                cell = self.cell_of(col, row)
                name = self.cell_to_name.get(cell) if cell is not None else None
                yield (col, row, cell, name)


def _find_default_keymap() -> Path | None:
    candidates = [
        USER_CONFIG / "keymap.json",
        *(d / "keymaps" / "ph16-71.json" for d in SHARE_DIRS),
        Path(__file__).resolve().parent.parent / "cli" / "keymaps" / "ph16-71.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ------------------------------------------------------------------ Frame helper

def frame_to_rgb(frame: bytes, num_cells: int = 128) -> list[tuple[int, int, int]]:
    """Decode a 384-byte frame into a list of (R, G, B) tuples, one per cell.
    Missing / short input is zero-padded.
    """
    out: list[tuple[int, int, int]] = []
    for i in range(num_cells):
        r = frame[i * 3 + 0] if i * 3 + 0 < len(frame) else 0
        g = frame[i * 3 + 1] if i * 3 + 1 < len(frame) else 0
        b = frame[i * 3 + 2] if i * 3 + 2 < len(frame) else 0
        out.append((r, g, b))
    return out


def rgb_to_frame(rgb: list[tuple[int, int, int]], num_cells: int = 128) -> bytes:
    buf = bytearray(num_cells * 3)
    for i, (r, g, b) in enumerate(rgb[:num_cells]):
        buf[i * 3 + 0] = r & 0xff
        buf[i * 3 + 1] = g & 0xff
        buf[i * 3 + 2] = b & 0xff
    return bytes(buf)
