# SPDX-License-Identifier: GPL-2.0-only
"""Battery tab: capacity hero + tabular pack details + health controls.

Layout, top to bottom:
  * a capacity hero (big %, status, and a block bar)
  * a bordered rich Table of pack details (voltages/charges humanised
    into V / A / mAh instead of raw micro-units)
  * a health panel (80% cap, calibration, end threshold, pack wear)
  * the limit / calibration action buttons
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static
from rich.table import Table

from tui_widgets import Panel, InfoButton


class BatteryTabMixin:
    """Compose + behaviour for the Battery tab. Mixed into PredatorSenseApp."""

    def _compose_battery(self) -> ComposeResult:
        yield InfoButton(
            "Battery health control. The PH16-71 firmware supports an "
            "80% charge cap (extends pack lifespan) + a one-shot "
            "calibration cycle. Cap & calibration go through our kernel "
            "module; the rest reads /sys/class/power_supply/BAT1/."
        )
        with Panel(title="◆ BATTERY", variant="magenta"):
            with Horizontal(classes="bat-cols"):
                yield Static("", id="bat_capacity", classes="bat-hero")
                yield Static("…", id="bat_body")
        with Panel(title="◆ HEALTH", variant="green"):
            yield Static("…", id="bat_health", classes="bat-health")
            with Horizontal(classes="btn-row"):
                yield Button("Limit ON  (80%)", id="bat_limit_on",  variant="primary")
                yield Button("Limit OFF (100%)", id="bat_limit_off")
                yield Button("Refresh",          id="bat_refresh")
            with Horizontal(classes="btn-row"):
                yield Button("Calibration: start", id="bat_calib_on", variant="warning")
                yield Button("Calibration: stop",  id="bat_calib_off")
            yield InfoButton(
                "Calibration runs one full discharge → charge cycle to "
                "re-learn the pack's capacity. Don't unplug AC mid-cycle."
            )

    def _battery_handle_button(self, bid: str, event) -> bool:
        if bid == "bat_limit_on":
            self._run_cli(lambda: self.client.set_health_mode(True))
            self.call_after_refresh(self._refresh_battery)
        elif bid == "bat_limit_off":
            self._run_cli(lambda: self.client.set_health_mode(False))
            self.call_after_refresh(self._refresh_battery)
        elif bid == "bat_calib_on":
            self._run_cli(lambda: self.client.set_calibration_mode(True))
            self.call_after_refresh(self._refresh_battery)
        elif bid == "bat_calib_off":
            self._run_cli(lambda: self.client.set_calibration_mode(False))
            self.call_after_refresh(self._refresh_battery)
        elif bid == "bat_refresh":
            self._refresh_battery()
        else:
            return False
        return True

    # ---------- value humanising

    @staticmethod
    def _humanise(key: str, raw: str) -> str:
        """Turn raw sysfs micro-units into readable V / A / mAh. Falls
        back to the raw string for anything non-numeric (model, status…)."""
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return raw
        if key == "voltage_now":
            return f"{n / 1_000_000:.2f} V"
        if key == "current_now":
            return f"{n / 1_000_000:+.2f} A"
        if key in ("charge_full", "charge_full_design", "charge_now"):
            return f"{n / 1000:.0f} mAh"
        return str(n)

    # ---------- refresh

    def _refresh_battery(self) -> None:
        try:
            info = self.client.get_battery_info()
        except Exception as e:
            self.query_one("#bat_body", Static).update(f"[red]error:[/] {e}")
            return

        # ---- capacity hero
        cap = info.get("capacity")
        status = info.get("status", "?")
        try:
            capn = int(cap)
        except (TypeError, ValueError):
            capn = None
        if capn is not None:
            width = 22
            filled = max(0, min(width, round(capn / 100 * width)))
            hue = "red" if capn < 20 else "yellow" if capn < 40 else "#3df5a0"
            bar = (f"[{hue}]" + "█" * filled + "[/]"
                   f"[dim]" + "░" * (width - filled) + "[/]")
            self.query_one("#bat_capacity", Static).update(
                f"[b]{capn}%[/]   [dim]{status}[/]\n{bar}"
            )
        else:
            self.query_one("#bat_capacity", Static).update("[dim]no capacity reading[/]")

        # ---- pack details table
        pack = Table.grid(padding=(0, 2))
        pack.add_column(justify="right", style="#9a7fc7", no_wrap=True)
        pack.add_column(justify="left", style="bold #ffffff")
        for key, label in (
            ("manufacturer",       "manufacturer"),
            ("model_name",         "model"),
            ("technology",         "technology"),
            ("status",             "status"),
            ("voltage_now",        "voltage"),
            ("current_now",        "current"),
            ("charge_now",         "charge now"),
            ("charge_full",        "charge full"),
            ("charge_full_design", "design full"),
        ):
            v = info.get(key)
            if v is not None:
                pack.add_row(label, self._humanise(key, v))
        self.query_one("#bat_body", Static).update(pack)

        # ---- health panel
        health = Table.grid(padding=(0, 2))
        health.add_column(justify="right", style="bold", no_wrap=True)
        health.add_column(justify="left")
        hm     = info.get("health_mode")
        calib  = info.get("calibration_mode")
        thresh = info.get("charge_control_end_threshold")
        if hm is None and thresh is None:
            self.query_one("#bat_health", Static).update(
                "[yellow]venator battery driver not bound — "
                "is the kernel module loaded?[/]"
            )
        else:
            health.add_row(
                "80% cap",
                "[#3df5a0]ON[/]" if hm == "1" else "[dim]off[/]",
            )
            health.add_row(
                "calibration",
                "[yellow]RUNNING[/]" if calib == "1" else "[dim]idle[/]",
            )
            if thresh is not None:
                health.add_row("end threshold", f"{thresh}%")
            # Pack wear = how much design capacity is left.
            try:
                full   = int(info["charge_full"])
                design = int(info["charge_full_design"])
                if design > 0:
                    wear = full / design * 100
                    whue = ("#3df5a0" if wear > 85
                            else "#ffd400" if wear > 70 else "#ff6b6b")
                    health.add_row("pack health", f"[{whue}]{wear:.0f}%[/] of design")
            except (KeyError, ValueError, ZeroDivisionError):
                pass
            self.query_one("#bat_health", Static).update(health)
