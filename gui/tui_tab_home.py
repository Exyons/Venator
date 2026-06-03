# SPDX-License-Identifier: GPL-2.0-only
"""Home tab: gradient hero banner + a 2x2 grid of live status cards.

Neon Predator look. The banner is a magenta->cyan ANSI-Shadow wordmark
(see tui_widgets.NeonBanner); below it sit four heavy-bordered cards —
Keyboard / Power / Battery / Lightbar — each refreshed at 2 Hz with live
state pulled straight from sysfs via the client.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Static

from tui_common import todays_tagline
from tui_widgets import NeonBanner


class HomeTabMixin:
    """Compose + refresh for the Home tab. Mixed into PredatorSenseApp."""

    # Border title for each card, keyed by widget id.
    _HOME_CARDS = {
        "card_keyboard": "◆ KEYBOARD",
        "card_power":    "◆ POWER",
        "card_battery":  "◆ BATTERY",
        "card_lightbar": "◆ LIGHTBAR",
    }

    def _compose_home(self) -> ComposeResult:
        yield NeonBanner(
            "VENATOR",
            subtitle=f"  « glow harder »   {self.client.device_name().lower()} · armed",
            id="home_banner",
        )
        yield Static(f"{todays_tagline()}", id="home_tagline", classes="tagline")
        with Grid(id="home_cards"):
            yield Static("", id="card_keyboard", classes="neon-card card-kbd")
            yield Static("", id="card_power",    classes="neon-card card-pwr")
            yield Static("", id="card_battery",  classes="neon-card card-bat")
            yield Static("", id="card_lightbar", classes="neon-card card-lb")

    def _maybe_rotate_tagline(self) -> None:
        try:
            self.query_one("#home_tagline", Static).update(todays_tagline())
        except Exception:
            return

    def _refresh_home(self) -> None:
        # Border titles are idempotent; (re)set them each tick so a fresh
        # mount always shows them without a separate on_mount hook.
        for cid, title in self._HOME_CARDS.items():
            try:
                self.query_one(f"#{cid}", Static).border_title = title
            except Exception:
                pass
        try:
            mode  = self.client.get_mode() or "?"
            col   = self.client.get_color() or "—"
            bri   = self.client.get_brightness()
            pwr   = self.client.get_power_profile() or "?"
            fans  = self.client.get_fans()
            temps = self.client.get_temps()
            bat   = self.client.get_battery_info()
            lb    = (self.client.get_lightbar()
                     if self.client.lightbar_present() else {})
        except Exception as e:
            try:
                self.query_one("#card_keyboard", Static).update(f"[red]error:[/] {e}")
            except Exception:
                pass
            return

        # ---- Keyboard card
        self.query_one("#card_keyboard", Static).update(
            f"[b]{mode}[/]\n"
            f"colour  [magenta]{col}[/]\n"
            f"bright  [yellow]{bri}[/]/255"
        )

        # ---- Power card (pretty profile name lives on the Power mixin)
        pretty = getattr(self, "POWER_LABELS", {}).get(pwr, pwr)
        top_t = max((temps.get(k, 0) for k in ("cpu_pkg", "cpu", "gpu")), default=0)
        thue  = "green" if top_t < 60 else "yellow" if top_t < 85 else "red"
        f1, f2 = fans.get(1, 0), fans.get(2, 0)
        self.query_one("#card_power", Static).update(
            f"[b]{pretty}[/]\n"
            f"cpu   [{thue}]{top_t}[/] °C\n"
            f"fans  {f1} / {f2} rpm"
        )

        # ---- Battery card (capacity bar + health cap)
        cap  = bat.get("capacity", "?")
        stat = bat.get("status", "?")
        hm   = bat.get("health_mode")
        hbit = ("limit [green]80%[/]" if hm == "1"
                else "limit [dim]off[/]" if hm == "0" else "")
        try:
            filled = max(0, min(8, round(int(cap) / 100 * 8)))
        except (ValueError, TypeError):
            filled = 0
        bar = "[green]" + "▰" * filled + "[/][dim]" + "▱" * (8 - filled) + "[/]"
        self.query_one("#card_battery", Static).update(
            f"[b]{cap}%[/]  ({stat})\n"
            f"{bar}\n"
            f"{hbit}"
        )

        # ---- Lightbar card
        if lb:
            lbcol = lb.get("color", "") or ""
            if lbcol and not lbcol.startswith("#"):
                lbcol = "#" + lbcol
            self.query_one("#card_lightbar", Static).update(
                f"[b]{lb.get('mode', '?')}[/]\n"
                f"colour  [cyan]{lbcol or '—'}[/]\n"
                f"bright  {lb.get('brightness', '?')}"
            )
        else:
            self.query_one("#card_lightbar", Static).update("[dim]not present[/]")
