#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""venator Textual TUI.

A terminal interface to the venator kernel module + CLI. Reads
the LED state directly from /sys (so the keyboard preview is live and
fast); shells out to `venator` for state-changing commands (so
all the auto-save / keepalive / animator behaviour stays canonical).

Run from a terminal:   venator tui
Quit:                  q  (or Ctrl-C)

This file is the thin assembly point. The actual UI is split into
focused modules in the same directory:

    tui_common.py      colour parsing, theme list, taglines
    tui.tcss           the App-level CSS (loaded via CSS_PATH)
    tui_widgets.py     ColorPopup / KeyboardView / StatusBar / ButtonGrid / FanSpinner
    tui_tab_home.py    Home tab
    tui_tab_keyboard.py    Keyboard tab (preview + effects/designs/anim/profiles/paint)
    tui_tab_power.py   Power tab (profile + AC/battery policy + fans/temps)
    tui_tab_battery.py Battery tab
    tui_tab_lightbar.py    Lightbar tab
    tui_tab_unified.py Unified keyboard+lightbar tab

PredatorSenseApp composes one mixin per tab. Each tab owns its own
compose / refresh / button-routing; this file keeps only the cross-tab
glue: the central event dispatchers, the colour-popup helper, the
worker-thread CLI runner, and the global key actions.
"""
from __future__ import annotations

import os
import sys

# Make the sibling modules importable when we're run via the
# /usr/local/bin launcher (which execs this file directly).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fail early + friendly if Textual isn't installed, before any of the
# submodules try to import it.
try:
    import textual  # noqa: F401
except ImportError as e:
    sys.stderr.write(
        f"Missing dependency for the TUI: {e}\n"
        f"  Fedora:    sudo dnf install python3-textual\n"
        f"  pip:       pip install --user textual\n"
    )
    sys.exit(1)

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.theme import Theme
from textual.widgets import (
    Header, Footer, Button, Input, Static, TabbedContent, TabPane,
)

from client import PredatorSenseClient, KeyboardLayout, frame_to_rgb
from tui_common import THEMES, parse_color, _norm_hex
from tui_widgets import ColorPopup, KeyboardView
from tui_tab_home import HomeTabMixin
from tui_tab_keyboard import KeyboardTabMixin
from tui_tab_power import PowerTabMixin
from tui_tab_battery import BatteryTabMixin
from tui_tab_lightbar import LightbarTabMixin
from tui_tab_unified import UnifiedTabMixin


# Neon Predator — the signature look. Magenta + cyan accents over a
# violet-black field. Registered + applied in on_mount so it's the
# startup theme; `t` cycles it against Textual's built-ins (see THEMES).
NEON_PREDATOR = Theme(
    name="neon-venator",
    primary="#ff2e97",      # magenta — headers, card borders, tab bar
    secondary="#00e5ff",    # cyan — lightbar, secondary accents
    accent="#f7b32b",       # hot amber — taglines, highlights
    foreground="#f5e8ff",
    background="#0d0221",    # violet-black field
    surface="#1a0b2e",      # card background
    panel="#2a1245",        # raised panels
    success="#3df5a0",
    warning="#f7b32b",
    error="#ff4365",
    dark=True,
    variables={
        "block-cursor-foreground":   "#0d0221",
        "block-cursor-background":    "#ff2e97",
        "block-cursor-text-style":    "bold",
        "footer-key-foreground":      "#00e5ff",
        "input-selection-background": "#ff2e97 35%",
        # Kill the reverse-video flash on a focused/pressed button —
        # bold alone reads cleaner against the neon palette.
        "button-focus-text-style":    "bold",
    },
)


class PredatorSenseApp(
    HomeTabMixin,
    KeyboardTabMixin,
    PowerTabMixin,
    BatteryTabMixin,
    LightbarTabMixin,
    UnifiedTabMixin,
    App,
):
    # App-level styling lives in tui.tcss next to this file. Textual
    # resolves CSS_PATH relative to the module that defines the App.
    CSS_PATH = "tui.tcss"

    BINDINGS = [
        Binding("q",      "quit",         "Quit"),
        Binding("escape", "quit",         "Quit"),
        Binding("ctrl+r", "refresh",      "Refresh"),
        Binding("t",      "cycle_theme",  "Theme"),
        Binding("?",      "help",         "Help"),
    ]

    selected_cell = reactive(None)
    selected_name = reactive(None)

    def __init__(self):
        super().__init__()
        try:
            self.client = PredatorSenseClient()
        except RuntimeError as e:
            sys.stderr.write(f"venator tui: {e}\n")
            sys.exit(1)
        self.kbd_layout = KeyboardLayout()
        self._paint_buf: list[tuple[int, int, int]] = (
            frame_to_rgb(self.client.get_frame(), self.kbd_layout.num_cells)
        )
        # Last colour the user picked, so the popup pre-fills and
        # palette effects (where the kernel ignores it anyway) still
        # receive a sensible value if reused.
        cur = self.client.get_color()
        self.last_color: str = cur if cur and parse_color(cur) else "#ff0000"
        # Recently-applied colours (most-recent-first), surfaced as
        # clickable chips in the colour popup.
        self.recent_colors: list[str] = []
        # Debounce timers for the global Brightness / Timeout inputs.
        # We keep one Timer reference per input; on each keystroke we
        # cancel + reschedule so a flurry of typing only writes once.
        self._brightness_debounce = None
        self._timeout_debounce    = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="home"):
            with TabPane("HOME",     id="home"):
                yield from self._compose_home()
            with TabPane("KEYBOARD", id="keyboard"):
                yield from self._compose_keyboard()
            with TabPane("POWER",    id="power"):
                yield from self._compose_power()
            with TabPane("BATTERY",  id="battery"):
                yield from self._compose_battery()
            with TabPane("LIGHTBAR", id="lightbar"):
                yield from self._compose_lightbar()
            with TabPane("UNIFIED",  id="unified"):
                yield from self._compose_unified()
        # Slim at-a-glance strip above the key-hint footer — recovers the
        # live profile / temp / brightness the old top bar used to show.
        yield Static("", id="livestat")
        yield Footer()

    async def on_mount(self) -> None:
        # Register + apply the Neon Predator theme before any refresh so
        # the first paint already carries the palette.
        self.register_theme(NEON_PREDATOR)
        self.theme = "neon-venator"
        self.title = "venator"
        self.sub_title = self.client.device_name()
        await self._reload_profile_list()
        # Live updates for the data-driven tabs. 1Hz is enough for human
        # eyes and cheap on the EC (each tick = 2 sysfs reads + 1
        # platform profile read). FanSpinner runs its own 20Hz visual
        # loop on the rpm value we set here.
        self._refresh_home()
        self._refresh_power()
        self._refresh_thermal()
        self._refresh_battery()
        # First mount: pull live kernel state into the lightbar inputs.
        # Subsequent timer ticks ONLY refresh the status line so a
        # user typing in the brightness/speed inputs doesn't get
        # their value clobbered every 5s.
        self._refresh_lightbar(sync_inputs=True)
        self._refresh_unified()
        self.set_interval(1.0, self._refresh_thermal)
        self.set_interval(2.0, self._refresh_battery)
        self.set_interval(2.0, self._refresh_home)
        self.set_interval(3.0, self._refresh_power)
        self.set_interval(5.0, self._refresh_lightbar)
        # Refresh the home tagline at the next local midnight so the
        # day-rotating phrase doesn't stick. Recheck every 60 s; cheap
        # and dodges DST / time-change weirdness.
        self.set_interval(60.0, self._maybe_rotate_tagline)
        self._refresh_livestat()
        self.set_interval(2.0, self._refresh_livestat)

    # ---------- central event dispatch
    #
    # Textual delivers each message type to a single App-level handler,
    # so the per-tab button routing lives in `_<tab>_handle_button`
    # methods on the mixins and we fan out to them here in tab order.
    # (on_input_changed / on_list_view_selected live on the keyboard
    # mixin and on_checkbox_changed on the power mixin — each is unique
    # so they resolve cleanly via the MRO.)

    def on_slider_changed(self, event) -> None:
        # The keyboard brightness slider auto-saves (debounced). The
        # lightbar / colour-popup sliders are read on demand, so they're
        # ignored here.
        if event.slider.id == "kb_brightness":
            self._kb_brightness_changed()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if await self._kb_handle_button(bid, event):
            return
        for handler in (
            self._power_handle_button,
            self._battery_handle_button,
            self._lightbar_handle_button,
            self._unified_handle_button,
        ):
            if handler(bid, event):
                return

    # ---------- shared helpers used across tabs

    def _color_or_warn(self, widget_id: str) -> str | None:
        val = self.query_one(f"#{widget_id}", Input).value
        norm = _norm_hex(val)
        if not norm:
            self.notify(f"Invalid colour {val!r}; expected #RRGGBB", severity="error")
            return None
        return norm

    def _int_or(self, widget_id: str, default: int) -> int:
        val = self.query_one(f"#{widget_id}", Input).value.strip()
        try:
            return int(val)
        except ValueError:
            return default

    def _ask_color_then(self, on_pick, *, title: str = "Pick a colour") -> None:
        """Open the colour popup; on apply, cache the value as
        self.last_color and invoke `on_pick(color)`. Cancels are
        ignored silently."""
        def _cb(value: str | None) -> None:
            if value is None:
                return
            self.last_color = value
            # Push onto the recents list (most-recent-first, de-duped, cap 6).
            self.recent_colors = (
                [value] + [c for c in self.recent_colors if c != value]
            )[:6]
            on_pick(value)
        self.push_screen(
            ColorPopup(self.last_color, recents=self.recent_colors, title=title),
            _cb,
        )

    def _run_cli(self, fn) -> None:
        """Run a state-changing CLI call in a worker thread so the UI
        stays responsive while subprocess + the kernel module work.
        """
        def _go() -> None:
            try:
                r = fn()
                if r.returncode != 0:
                    msg = r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}"
                    self.call_from_thread(self.notify,
                        f"CLI failed: {msg}", severity="error")
            except Exception as e:
                self.call_from_thread(self.notify,
                    f"CLI exception: {e}", severity="error")
            finally:
                self.call_from_thread(self._refresh_preview)
        import threading
        threading.Thread(target=_go, daemon=True).start()

    def _refresh_preview(self) -> None:
        view = self.query_one("#kbview", KeyboardView)
        view._poll()

    def _refresh_livestat(self) -> None:
        """Update the slim status strip above the footer."""
        try:
            pwr = self.client.get_power_profile() or "?"
            pretty = getattr(self, "POWER_LABELS", {}).get(pwr, pwr)
            temps = self.client.get_temps()
            top_t = max((temps.get(k, 0) for k in ("cpu_pkg", "cpu")), default=0)
            bri = self.client.get_brightness()
            ac = self.client.on_ac_power()
            plug = "AC" if ac is True else "BAT" if ac is False else "—"
            self.query_one("#livestat", Static).update(
                f"[#f7b32b]{pretty}[/]  ·  [#00e5ff]{top_t}°[/]  ·  "
                f"bright [#f5e8ff]{bri}[/]  ·  [dim]{plug}[/]   "
            )
        except Exception:
            self.query_one("#livestat", Static).update("[dim]status unavailable[/]")

    # ---------- global key actions

    async def action_refresh(self) -> None:
        self._refresh_preview()
        await self._reload_profile_list()

    def action_cycle_theme(self) -> None:
        try:
            idx = THEMES.index(self.theme)
        except ValueError:
            idx = -1
        nxt = THEMES[(idx + 1) % len(THEMES)]
        self.theme = nxt
        self.notify(f"Theme: {nxt}", timeout=2)

    def action_help(self) -> None:
        self.notify(
            "Tabs: cycle with click or arrows. Click a key in the preview "
            "to select it for the Paint tab. t=theme, q/Esc=quit.",
            timeout=8,
        )


def main() -> int:
    try:
        PredatorSenseApp().run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
