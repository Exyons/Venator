# SPDX-License-Identifier: GPL-2.0-only
"""Power tab: platform profile, AC/battery policy, and live fans/temps.

Two columns — power controls (left, scrollable) and the live fan discs
+ temperatures (right).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.widgets import Button, Checkbox, Static

from tui_widgets import ButtonGrid, FanSpinner, Panel, InfoButton


class PowerTabMixin:
    """Compose + behaviour for the Power tab. Mixed into PredatorSenseApp."""

    # Profiles offered in the policy/profile grids, low → high power.
    _PWR_PROFILE_ORDER = ("low-power", "quiet", "balanced",
                          "balanced-performance", "performance")
    # Raw names that are NOT allowed on battery without Advanced.
    _BATTERY_HIGH_POWER = ("balanced-performance", "performance")

    # Map the raw kernel platform_profile names to the PredatorSense /
    # user-facing names. The right column is what the firmware actually
    # accepts; the left is what gamers expect to see. We rename
    # `performance` -> "Turbo" and `balanced-performance` -> "Performance"
    # to match PredatorSense Windows.
    POWER_LABELS = {
        "low-power":             "Eco",
        "quiet":                 "Quiet",
        "balanced":              "Balanced",
        "balanced-performance":  "Performance",
        "performance":           "Turbo",
    }

    # ---------- compose

    def _compose_power(self) -> ComposeResult:
        # Two columns: left = power controls, right = live fans + temps.
        # The left column scrolls so its buttons are never clipped on
        # short terminals (this was the "cramped, can't see them" bug).
        with Horizontal(id="pwr_columns"):
            with ScrollableContainer(classes="pwr-col", id="pwr_col_left"):
                yield InfoButton(
                    "Power / thermal profile. Names map to PredatorSense as: "
                    "Eco=low-power, Quiet, Balanced, Performance="
                    "balanced-performance, Turbo=performance."
                )
                with Panel(title="◆ PROFILE", variant="amber"):
                    yield Static("current: …", id="pwr_current")
                    yield Static("managers: …", id="pwr_ppd")
                    yield ButtonGrid(*[
                        Button(label, id=f"pwr_set_{val}", variant=variant)
                        for label, val, variant in [
                            ("Eco",          "low-power",            "default"),
                            ("Quiet",        "quiet",                "default"),
                            ("Balanced",     "balanced",             "primary"),
                            ("Performance",  "balanced-performance", "warning"),
                            ("Turbo",        "performance",          "error"),
                        ]
                    ], id="pwr_grid")
                    with Horizontal(classes="btn-row"):
                        yield Button("Detach mgrs", id="pwr_detach_ppd", variant="warning")
                        yield Button("Attach mgrs", id="pwr_attach_ppd")
                        yield Button("Refresh",     id="pwr_refresh")

                # ---- Per-source policy: separate AC / battery profile,
                #      restored at login AND switched live on plug/unplug
                #      by the powerwatch service.
                with Panel(title="◆ AUTO PROFILE  ·  boot + plug/unplug",
                           variant="cyan"):
                    yield InfoButton(
                        "Profile to use when plugged in vs on battery. On "
                        "battery only Eco/Quiet/Balanced are allowed — tick "
                        "Advanced to also allow Performance/Turbo."
                    )
                    yield Static("policy: …", id="ppol_status")
                    yield Static("On AC power", classes="subhead")
                    yield ButtonGrid(*[
                        Button(self.POWER_LABELS[val], id=f"ppol_ac_{val}")
                        for val in self._PWR_PROFILE_ORDER
                    ], id="ppol_ac_grid")
                    yield Static("On battery", classes="subhead")
                    yield ButtonGrid(*[
                        Button(self.POWER_LABELS[val], id=f"ppol_bat_{val}",
                               disabled=(val in self._BATTERY_HIGH_POWER))
                        for val in self._PWR_PROFILE_ORDER
                    ], id="ppol_bat_grid")
                    yield Checkbox("Advanced (allow Performance/Turbo on battery)",
                                   id="ppol_advanced", value=False)
                    # Inline warning line (replaces the old confirmation popup).
                    yield Static(
                        "[dim]Tick Advanced above to enable Performance/Turbo "
                        "on battery.[/]", id="ppol_adv_hint", classes="small")

            with ScrollableContainer(classes="pwr-col", id="pwr_col_right"):
                with Panel(title="◆ FANS", variant="magenta"):
                    with Horizontal(classes="fans-row"):
                        yield FanSpinner("fan1", "left / CPU blower",  id="fan1_spin")
                        yield FanSpinner("fan2", "right / GPU blower", id="fan2_spin")
                with Panel(title="◆ TEMPS", variant="green"):
                    yield Static("…", id="thermal_temps")

    # ---------- button routing for this tab

    def _power_handle_button(self, bid: str, event) -> bool:
        if bid.startswith("pwr_set_"):
            profile = bid.removeprefix("pwr_set_")
            self._run_cli(lambda: self.client.set_power_profile(profile))
            self.call_after_refresh(self._refresh_power)
        elif bid == "pwr_detach_ppd":
            self._run_cli(self.client.detach_ppd)
            self.call_after_refresh(self._refresh_power)
        elif bid == "pwr_attach_ppd":
            self._run_cli(self.client.attach_ppd)
            self.call_after_refresh(self._refresh_power)
        elif bid == "pwr_refresh":
            self._refresh_power()
        elif bid.startswith("ppol_ac_"):
            self._set_power_policy("ac", bid.removeprefix("ppol_ac_"))
        elif bid.startswith("ppol_bat_"):
            self._set_power_policy_battery(bid.removeprefix("ppol_bat_"))
        else:
            return False
        return True

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "ppol_advanced":
            self._apply_advanced_state(event.value)

    # ---------- policy actions

    def _set_power_policy(self, slot: str, profile: str,
                          advanced: bool = False) -> None:
        self._run_cli(
            lambda: self.client.set_power_policy(slot, profile, advanced))
        self.call_after_refresh(self._refresh_power_policy)

    def _set_power_policy_battery(self, profile: str) -> None:
        """Battery slot. Eco/Quiet/Balanced go straight through. The
        high-power profiles are only reachable when the Advanced
        checkbox is ticked (the inline warning line spells out the
        battery-wear cost), so a click on an enabled Turbo/Performance
        button applies it directly with --advanced.
        """
        if profile in ("low-power", "quiet", "balanced"):
            self._set_power_policy("battery", profile)
        else:
            # Only reachable when Advanced is on (button is disabled
            # otherwise). The warning line is already visible.
            self._set_power_policy("battery", profile, advanced=True)
            pretty = self.POWER_LABELS.get(profile, profile)
            self.notify(f"On-battery profile set to {pretty} (battery wear ↑).",
                        severity="warning", timeout=5)

    def _apply_advanced_state(self, advanced: bool) -> None:
        """Enable/disable the battery Performance/Turbo buttons and update
        the warning line, in one place so the checkbox handler and the
        periodic refresh stay in sync."""
        for val in self._BATTERY_HIGH_POWER:
            try:
                self.query_one(f"#ppol_bat_{val}", Button).disabled = not advanced
            except Exception:
                pass
        try:
            hint = self.query_one("#ppol_adv_hint", Static)
            if advanced:
                hint.update("[b yellow]⚠ Performance/Turbo on battery spins the "
                            "fans hard, drains the pack fast, and accelerates "
                            "battery wear.[/]")
            else:
                hint.update("[dim]Tick Advanced above to enable "
                            "Performance/Turbo on battery.[/]")
        except Exception:
            pass

    # ---------- refresh

    def _refresh_power(self) -> None:
        try:
            cur = self.client.get_power_profile() or "?"
            choices = self.client.get_power_profile_choices()
            pretty_cur = self.POWER_LABELS.get(cur, cur)
            pretty_choices = " ".join(
                self.POWER_LABELS.get(c, c) for c in choices
            ) if choices else "(none)"
            self.query_one("#pwr_current", Static).update(
                f"current: [b cyan]{pretty_cur}[/]   "
                f"[dim]raw:[/] {cur}   "
                f"[dim]choices:[/] {pretty_choices}"
            )
            # Report every known power manager that's active — PPD, tuned,
            # auto-cpufreq, etc. — since any of them revert our profile on
            # AC change. If any is active we highlight it (it'll fight the
            # powerwatch daemon); all-masked means we own the profile.
            import subprocess as _sp
            units = [
                ("PPD",          "power-profiles-daemon.service"),
                ("tuned",        "tuned.service"),
                ("auto-cpufreq", "auto-cpufreq.service"),
                ("system76",     "system76-power.service"),
                ("tlp",          "tlp.service"),
            ]
            active = [name for name, unit in units
                      if _sp.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0]
            if active:
                self.query_one("#pwr_ppd", Static).update(
                    f"managers: [yellow]{', '.join(active)} active[/] "
                    f"[dim](may revert on AC change — click Detach mgrs)[/]"
                )
            else:
                self.query_one("#pwr_ppd", Static).update(
                    "managers: [green]none active[/] "
                    "[dim](venator owns the profile)[/]"
                )
        except Exception as e:
            self.query_one("#pwr_current", Static).update(f"[red]error:[/] {e}")
        self._refresh_power_policy()

    def _refresh_power_policy(self) -> None:
        """Update the AC/battery policy status line + reflect the
        Advanced checkbox state onto the battery high-power buttons.
        """
        try:
            pol = self.client.get_power_policy()
            on_ac = self.client.on_ac_power()
        except Exception:
            return
        src = ("AC" if on_ac is True else
               "battery" if on_ac is False else "unknown")
        ac_p  = self.POWER_LABELS.get(pol.get("ac"),  pol.get("ac") or "—")
        bat_p = self.POWER_LABELS.get(pol.get("battery"), pol.get("battery") or "—")
        try:
            self.query_one("#ppol_status", Static).update(
                f"source: [b cyan]{src}[/]   "
                f"[dim]AC →[/] {ac_p}   [dim]battery →[/] {bat_p}"
            )
        except Exception:
            return
        # Enable/disable battery high-power buttons per the Advanced toggle.
        try:
            advanced = self.query_one("#ppol_advanced", Checkbox).value
            self._apply_advanced_state(advanced)
        except Exception:
            pass

    def _refresh_thermal(self) -> None:
        try:
            fans = self.client.get_fans()
            temps = self.client.get_temps()
            # Push to spinners
            for i, sid in ((1, "#fan1_spin"), (2, "#fan2_spin")):
                w = self.query_one(sid, FanSpinner)
                w.rpm = fans.get(i, 0)
            # Temperatures
            lines = []
            order = [
                ("cpu",     "CPU      (acer/temp1, EC CTMP)"),
                ("gpu",     "GPU      (acer/temp2, EC GTMP)"),
                ("chassis", "chassis  (acer/temp3, EC STMP)"),
                ("cpu_pkg", "cpu pkg  (coretemp / k10temp, die)"),
                ("nvme",    "nvme     (Composite)"),
            ]
            for key, label in order:
                v = temps.get(key)
                if v is None:
                    if key == "gpu":
                        lines.append(f"  {label:40s}  [dim]—  (D3cold)[/]")
                    continue
                hue = "green" if v < 60 else "yellow" if v < 85 else "red"
                lines.append(f"  {label:40s}  [{hue}]{v:>3}[/] °C")
            self.query_one("#thermal_temps", Static).update("\n".join(lines) or "(no readings)")
        except Exception as e:
            self.query_one("#thermal_temps", Static).update(f"[red]error:[/] {e}")
