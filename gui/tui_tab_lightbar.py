# SPDX-License-Identifier: GPL-2.0-only
"""Lightbar tab: rear EC RGB strip (WMBH AcerGamingFunction)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, Static

from tui_widgets import ColorPopup, Panel, Slider, InfoButton


class LightbarTabMixin:
    """Compose + behaviour for the Lightbar tab. Mixed into PredatorSenseApp."""

    def _compose_lightbar(self) -> ComposeResult:
        yield InfoButton(
            "Rear lightbar control. Driven by the EC via WMBH "
            "AcerGamingFunction (method 20). 8 effect modes — pick one, "
            "set the colour + brightness + speed, click Apply."
        )

        # Current state line
        yield Static("…", id="lb_status")

        # Mode picker — one button per mode, more discoverable than a dropdown.
        with Panel(title="◆ MODE", variant="cyan"):
            with Horizontal(classes="btn-row"):
                yield Button("Off",       id="lb_mode_off",       variant="error")
                yield Button("Static",    id="lb_mode_static",    variant="primary")
                yield Button("Breathing", id="lb_mode_breathing")
                yield Button("Neon",      id="lb_mode_neon")
            with Horizontal(classes="btn-row"):
                yield Button("Rainbow",   id="lb_mode_rainbow")
                yield Button("Wave",      id="lb_mode_wave")
                yield Button("Ripple",    id="lb_mode_ripple")
                yield Button("Scanner",   id="lb_mode_scanner")
            with Horizontal(classes="btn-row"):
                yield Button("Strobe",    id="lb_mode_strobe")

        # Colour + brightness + speed inputs. `lb-row` class gives wider
        # inputs and trims the default Input padding that was making the
        # row look unbalanced compared to the value area.
        with Panel(title="◆ COLOUR & PARAMETERS", variant="magenta"):
            with Horizontal(classes="row lb-row"):
                yield Label("Colour:")
                yield Input(value="ff0000", id="lb_color",
                            placeholder="RRGGBB", classes="lb-color")
                yield Button("◉", id="lb_color_pick", classes="icon-btn")
            with Horizontal(classes="slider-row"):
                yield Label("Brightness:")
                yield Slider(100, min=0, max=255, step=5, id="lb_brightness")
            with Horizontal(classes="slider-row"):
                yield Label("Speed:")
                yield Slider(5, min=0, max=255, step=5, id="lb_speed")
            with Horizontal(classes="btn-row"):
                yield Button("Apply",      id="lb_apply",   variant="success")
                yield Button("Refresh",    id="lb_refresh")
        yield InfoButton(
            "Effects: breathing = single-colour fade, neon = full-bar "
            "colour cycle, rainbow = per-zone rotation, wave = sequential "
            "fire, ripple = radiate from centre, scanner = left↔right sweep, "
            "strobe = warning flash."
        )

    def _lightbar_handle_button(self, bid: str, event) -> bool:
        if bid.startswith("lb_mode_"):
            self._apply_lightbar(mode=bid.removeprefix("lb_mode_"))
        elif bid == "lb_apply":
            self._apply_lightbar()
        elif bid == "lb_refresh":
            # Pull live values back into the inputs — explicit user action
            self._refresh_lightbar(sync_inputs=True)
        elif bid == "lb_color_pick":
            self._lightbar_color_picker()
        else:
            return False
        return True

    def _read_lb_inputs(self) -> dict:
        """Pull current values out of the colour/brightness/speed inputs."""
        out: dict = {}
        try:
            colour = self.query_one("#lb_color", Input).value.strip()
            if colour:
                out["hex_color"] = colour
        except Exception:
            pass
        try:
            out["brightness"] = int(self.query_one("#lb_brightness", Slider).value)
        except Exception:
            pass
        try:
            out["speed"] = int(self.query_one("#lb_speed", Slider).value)
        except Exception:
            pass
        return out

    def _apply_lightbar(self, *, mode: str | None = None) -> None:
        if not self.client.lightbar_present():
            self.notify("no /sys/class/predator/lightbar0 — kernel module not loaded?",
                        severity="warning", timeout=4)
            return
        kw = self._read_lb_inputs()
        if mode is not None:
            kw["mode"] = mode
        self._run_cli(lambda: self.client.set_lightbar(**kw))
        self.call_after_refresh(self._refresh_lightbar)

    def _lightbar_color_picker(self) -> None:
        """Open the colour popup. Uses push_screen+callback (not
        push_screen_wait) because the latter needs to be inside a
        textual Worker — button handlers aren't.
        """
        try:
            cur = self.query_one("#lb_color", Input).value or "ff0000"
        except Exception:
            cur = "ff0000"

        def _cb(value: str | None) -> None:
            if value is None:
                return
            try:
                self.query_one("#lb_color", Input).value = value.lstrip("#")
            except Exception:
                return
            self._apply_lightbar()

        self.push_screen(ColorPopup(cur, title="Lightbar colour"), _cb)

    def _refresh_lightbar(self, *, sync_inputs: bool = False) -> None:
        """Refresh the lightbar status line.

        By default ONLY updates the read-only status text — the user-
        editable Input widgets (colour / brightness / speed) are left
        alone so a periodic 5s tick doesn't undo whatever the user is
        typing. Call with sync_inputs=True from the Refresh button to
        explicitly pull current state back into the inputs.
        """
        try:
            state = self.client.get_lightbar()
            if not state:
                self.query_one("#lb_status", Static).update(
                    "[yellow]lightbar driver not bound — kernel module loaded?[/]")
                return
            mode   = state.get("mode", "?")
            colour = state.get("color", "?")
            b      = state.get("brightness", "?")
            sp     = state.get("speed", "?")
            self.query_one("#lb_status", Static).update(
                f"[dim]mode[/] [b cyan]{mode}[/]   ·   "
                f"[dim]colour[/] [b]#{colour}[/]   ·   "
                f"[dim]bright[/] [b]{b}[/]   ·   "
                f"[dim]speed[/] [b]{sp}[/]")
            if sync_inputs:
                try:
                    self.query_one("#lb_color", Input).value = colour
                except Exception:
                    pass
                try:
                    self.query_one("#lb_brightness", Slider).value = int(b)
                except (ValueError, Exception):
                    pass
                try:
                    self.query_one("#lb_speed", Slider).value = int(sp)
                except (ValueError, Exception):
                    pass
        except Exception as e:
            self.query_one("#lb_status", Static).update(
                f"[red]refresh failed: {e}[/]")
