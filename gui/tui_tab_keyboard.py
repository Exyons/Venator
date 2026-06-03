# SPDX-License-Identifier: GPL-2.0-only
"""Keyboard tab: live preview, global controls, and the inner
Effects / Designs / Animations / Profiles / Paint sub-tabs.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import (
    Button, Input, Label, Static, ListView, ListItem, TabbedContent, TabPane,
)

from client import frame_to_rgb, rgb_to_frame
from tui_widgets import KeyboardView, ButtonGrid, Panel, Slider, InfoButton


class KeyboardTabMixin:
    """Compose + behaviour for the Keyboard tab. Mixed into PredatorSenseApp.

    Relies on these helpers provided by the core App: _run_cli,
    _refresh_preview, _color_or_warn, _int_or, _ask_color_then, and the
    `last_color` / `selected_cell` / `selected_name` / `kbd_layout`
    attributes.
    """

    # Effects that take a single colour and would benefit from the
    # popup. Palette effects (rainbow / neon / explosion / stars) get
    # applied directly with the cached last colour as a no-op input.
    COLOR_EFFECTS = {"static", "breathing", "snake", "ripple",
                     "pulse", "meteor", "aura"}

    # Debounce window for the global Brightness / Timeout inputs. Timeout
    # has no global sysfs (it's a per-command CLI flag) so we cache it in
    # `last_timeout` for the next effect.
    DEBOUNCE_S = 0.75
    last_timeout = 0

    # ---------- compose

    def _compose_keyboard(self) -> ComposeResult:
        # Global controls. Both inputs auto-save after a short debounce
        # so the user doesn't need an Apply button. Seed them from the
        # current kernel state so the initial Input.Changed event (the
        # default-value one) is a no-op.
        try:
            init_bright = int(self.client.get_brightness())
        except Exception:
            init_bright = 200
        with Panel(title="◆ CONTROLS", variant="amber"):
            with Horizontal(classes="slider-row"):
                yield Label("Brightness:")
                yield Slider(init_bright, min=0, max=255, step=5, id="kb_brightness")
            with Horizontal(classes="row globals"):
                yield Label("Timeout:")
                yield Input(value=str(self.last_timeout), id="kb_timeout",
                            placeholder="0=off")
                yield Button("LEDs Off", id="kb_leds_off", variant="error")
                yield Button("Refresh",  id="kb_refresh_state")
        # Live preview of the matrix.
        with Panel(title="◆ LIVE PREVIEW", variant="cyan"):
            yield KeyboardView(self.client, self.kbd_layout, id="kbview")
        # Inner sub-tabs for the actual feature pickers.
        with TabbedContent(initial="effects", id="kb_inner"):
            with TabPane("EFFECTS",    id="effects"):
                yield from self._compose_effects()
            with TabPane("DESIGNS",    id="designs"):
                yield from self._compose_designs()
            with TabPane("ANIMATIONS", id="animations"):
                yield from self._compose_animations()
            with TabPane("PROFILES",   id="profiles"):
                yield from self._compose_profiles()
            with TabPane("PAINT KEYS", id="paint"):
                yield from self._compose_paint()

    def _compose_effects(self) -> ComposeResult:
        yield InfoButton(
            "Click an effect to apply. Solid + colour-driven effects pop a "
            "colour picker; the chosen colour is cached so you don't re-type "
            "it for the next one."
        )
        # The headline "Solid" button comes first so it's the obvious
        # primary action.
        with Horizontal(classes="btn-row"):
            yield Button("Solid (pick colour…)",
                         id="effect_static",
                         variant="success")
            yield Button("LEDs Off", id="btn_off", variant="error")
        modes = [m for m in self.client.available_modes()
                 if m not in ("off", "static", "perkey")]
        yield ButtonGrid(*[
            Button(mode.replace("_", " ").title(),
                   id=f"effect_{mode}",
                   variant="primary"
                   if mode in self.COLOR_EFFECTS else "default")
            for mode in modes
        ], id="effects_grid")

    def _compose_designs(self) -> ComposeResult:
        yield InfoButton(
            "Static per-key designs. Click to apply with the current "
            "brightness / timeout (see Controls)."
        )
        designs = self.client.list_designs()
        yield ButtonGrid(*[
            Button(name.replace("_", " ").title(),
                   id=f"design_{name}")
            for name in designs
        ], id="designs_grid")

    def _compose_animations(self) -> ComposeResult:
        yield InfoButton(
            "Custom animation scripts. Click to run; running animation is "
            "replaced by whatever you click next."
        )
        anims = self.client.list_animations()
        yield ButtonGrid(*[
            Button(name.replace("_", " ").title(),
                   id=f"anim_{name}",
                   variant="success")
            for name in anims
        ], id="anims_grid")

    def _compose_profiles(self) -> ComposeResult:
        yield InfoButton(
            "Save the current scheme under a name, or load a saved one. "
            "Every rgb command auto-saves the 'default' profile."
        )
        with Horizontal(classes="row"):
            yield Label("Profile:")
            yield Input(value="my-profile", id="profile_name",
                        placeholder="name")
        with Horizontal(classes="btn-row"):
            yield Button("Save",   id="btn_profile_save", variant="primary")
            yield Button("Load",   id="btn_profile_load")
            yield Button("Delete", id="btn_profile_delete", variant="error")
            yield Button("Refresh List", id="btn_profile_refresh")
        yield Static("[b]Saved profiles:[/]")
        yield ListView(id="profile_list")

    def _compose_paint(self) -> ComposeResult:
        yield InfoButton(
            "Per-key paint mode. Click a key in the preview above to select it, "
            "set a colour here, then 'Paint Selected' to set just that one, or "
            "'Apply All' to push the whole buffer."
        )
        yield Static("Selected key: [b]none[/]", id="paint_selected")
        with Horizontal(classes="row"):
            yield Label("Colour:")
            yield Input(value="#ff0000", id="paint_color", placeholder="#RRGGBB")
        with Horizontal(classes="btn-row"):
            yield Button("Paint Selected", id="btn_paint_one",   variant="primary")
            yield Button("Paint by Name",  id="btn_paint_by_name")
            yield Button("Apply Whole Buffer", id="btn_paint_all")
            yield Button("Reset Buffer",  id="btn_paint_reset", variant="error")
        with Horizontal(classes="row"):
            yield Label("Names:")
            yield Input(value="W,A,S,D", id="paint_names",
                        placeholder="comma-separated key names")

    # ---------- profile list

    async def _reload_profile_list(self) -> None:
        """Reload the profile ListView.

        ListView.clear() / .append() return awaitables; if we don't await
        clear() the appends queue up against children that haven't been
        removed yet, which then explodes on duplicate IDs. Doing this
        properly = make the function async and await clear.
        """
        lv = self.query_one("#profile_list", ListView)
        await lv.clear()
        for name in self.client.profile_list():
            await lv.append(ListItem(Label(name), id=f"profile_{name}"))

    # ---------- button routing for this tab

    async def _kb_handle_button(self, bid: str, event) -> bool:
        if bid in ("kb_leds_off", "btn_off"):
            self._run_cli(self.client.rgb_off)
        elif bid in ("kb_refresh_state", "btn_refresh_state"):
            self._refresh_preview()
        elif bid == "effect_static":
            # "Solid" — Static mode with a colour picked from the popup.
            self._apply_static()
        elif bid.startswith("effect_"):
            self._apply_effect(bid.removeprefix("effect_"))
        elif bid.startswith("design_"):
            self._apply_design(bid.removeprefix("design_"))
        elif bid.startswith("anim_"):
            self._apply_animation(bid.removeprefix("anim_"))
        elif bid == "btn_profile_save":
            name = self.query_one("#profile_name", Input).value.strip()
            if name:
                self._run_cli(lambda: self.client.profile_save(name))
                await self._reload_profile_list()
        elif bid == "btn_profile_load":
            name = self.query_one("#profile_name", Input).value.strip()
            if name:
                self._run_cli(lambda: self.client.profile_load(name))
        elif bid == "btn_profile_delete":
            name = self.query_one("#profile_name", Input).value.strip()
            if name:
                self._run_cli(lambda: self.client.profile_delete(name))
                await self._reload_profile_list()
        elif bid == "btn_profile_refresh":
            await self._reload_profile_list()
        elif bid == "btn_paint_one":
            self._paint_one()
        elif bid == "btn_paint_by_name":
            self._paint_by_name()
        elif bid == "btn_paint_all":
            self._paint_all()
        elif bid == "btn_paint_reset":
            self._paint_buf = frame_to_rgb(
                self.client.get_frame(), self.kbd_layout.num_cells,
            )
            self.notify("Paint buffer reset to current LED state.")
        else:
            return False
        return True

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id.startswith("profile_"):
            name = item_id.removeprefix("profile_")
            self.query_one("#profile_name", Input).value = name

    # ---------- auto-save brightness + timeout

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "kb_timeout":
            if self._timeout_debounce is not None:
                self._timeout_debounce.stop()
            self._timeout_debounce = self.set_timer(
                self.DEBOUNCE_S, self._commit_timeout)

    def _kb_brightness_value(self) -> int:
        """Current brightness from the slider (the global control)."""
        try:
            return int(self.query_one("#kb_brightness", Slider).value)
        except Exception:
            return 200

    def _kb_brightness_changed(self) -> None:
        """Debounced auto-save fired by the App when the slider moves —
        a flurry of drag events only writes once."""
        if self._brightness_debounce is not None:
            self._brightness_debounce.stop()
        self._brightness_debounce = self.set_timer(
            self.DEBOUNCE_S, self._commit_brightness)

    def _commit_brightness(self) -> None:
        val = self._kb_brightness_value()
        if not 0 <= val <= 255:
            return
        # Skip the write if the kernel already has this value. Prevents
        # the initial-mount Input.Changed event from triggering a
        # no-op CLI invocation, and also dedupes "typed 80, deleted to
        # 8, typed 0 again -> back to 80" sequences.
        try:
            if int(self.client.get_brightness()) == val:
                return
        except Exception:
            pass
        # Shell out via the same CLI the client uses — picks up the
        # right cli_path (handles /usr/local/bin vs /usr/bin).
        r = self.client._run("brightness", str(val), "--apply")
        if r.returncode != 0:
            self.notify(f"brightness write failed: "
                        f"{r.stderr.strip() or r.stdout.strip()}",
                        severity="error")
        else:
            self.notify(f"brightness → {val}", timeout=2)

    def _commit_timeout(self) -> None:
        try:
            val = int(self.query_one("#kb_timeout", Input).value.strip())
        except ValueError:
            return
        if not 0 <= val <= 60:
            self.notify("timeout must be 0..60", severity="warning", timeout=3)
            return
        if self.last_timeout == val:
            return
        self.last_timeout = val
        self.notify(f"timeout → {val}s (applies to next effect)", timeout=2)

    # ---------- cell clicks (fired from KeyboardView)

    def action_cell_clicked(self, cell: int) -> None:
        name = self.kbd_layout.cell_to_name.get(cell)
        self.selected_cell = cell
        self.selected_name = name
        label = f"cell [cyan]{cell}[/] (name: [b]{name or '—'}[/])"
        self.query_one("#paint_selected", Static).update(
            f"Selected key: {label}"
        )
        view = self.query_one("#kbview", KeyboardView)
        view.selected = cell
        # Hint the user where the selection landed.
        self.notify(
            f"Selected {name or 'cell ' + str(cell)} — switch to "
            "the Paint Keys tab to colour it.",
            timeout=2,
        )

    # ---------- effect / design / animation / paint actions

    def _apply_static(self) -> None:
        """Pop the colour picker, then run a static fill with the chosen
        colour. Reuses self.last_color as the popup's initial value so
        repeated picks are quick."""
        self._ask_color_then(lambda col: self._run_static(col),
                             title="Solid colour")

    def _run_static(self, col: str) -> None:
        b = self._kb_brightness_value()
        t = self._int_or("kb_timeout",     0)
        self._run_cli(lambda: self.client.rgb_static(col, brightness=b, timeout=t))

    def _apply_effect(self, mode: str) -> None:
        """Palette effects fire straight away; colour-driven effects
        pop the picker first so the user can change the hue per effect
        if they want. Cached `last_color` is the popup's prefill."""
        if mode in self.COLOR_EFFECTS:
            self._ask_color_then(
                lambda col: self._run_effect(mode, col),
                title=f"Colour for {mode.replace('_', ' ').title()}",
            )
        else:
            self._run_effect(mode, self.last_color)

    def _run_effect(self, mode: str, col: str | None) -> None:
        b = self._kb_brightness_value()
        t = self._int_or("kb_timeout",     0)
        self._run_cli(lambda: self.client.rgb_effect(
            mode, hex_color=col, brightness=b, timeout=t,
        ))

    def _apply_design(self, name: str) -> None:
        b = self._kb_brightness_value()
        t = self._int_or("kb_timeout",     0)
        self._run_cli(lambda: self.client.rgb_design(name, brightness=b, timeout=t))

    def _apply_animation(self, name: str) -> None:
        b = self._kb_brightness_value()
        t = self._int_or("kb_timeout",     0)
        self._run_cli(lambda: self.client.rgb_animate(name, brightness=b, timeout=t))

    def _paint_one(self) -> None:
        if self.selected_name is None:
            self.notify("No named key selected. Click a key in the preview "
                        "(some matrix cells have no key).", severity="warning")
            return
        col = self._color_or_warn("paint_color")
        if col is None:
            return
        b = self._kb_brightness_value()
        t = self._int_or("kb_timeout",     0)
        self._run_cli(lambda: self.client.rgb_key(
            self.selected_name, col, brightness=b, timeout=t,
        ))

    def _paint_by_name(self) -> None:
        names = [n.strip() for n in
                 self.query_one("#paint_names", Input).value.split(",")
                 if n.strip()]
        if not names:
            self.notify("Enter one or more key names, comma-separated.",
                        severity="warning")
            return
        col = self._color_or_warn("paint_color")
        if col is None:
            return
        b = self._kb_brightness_value()
        t = self._int_or("kb_timeout",     0)
        self._run_cli(lambda: self.client.rgb_keys(
            names, col, brightness=b, timeout=t,
        ))

    def _paint_all(self) -> None:
        frame = rgb_to_frame(self._paint_buf, self.kbd_layout.num_cells)
        b = self._kb_brightness_value()
        t = self._int_or("kb_timeout",     0)
        self._run_cli(lambda: self.client.rgb_perkey(
            frame, brightness=b, timeout=t,
        ))
