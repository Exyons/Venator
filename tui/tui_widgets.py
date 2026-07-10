# SPDX-License-Identifier: GPL-2.0-only
"""Reusable Textual widgets for the venator TUI.

- ColorPopup    modal colour picker
- KeyboardView  live 22x6 LED-matrix preview
- StatusBar     one-line current-state header
- ButtonGrid    reflowing button grid
- FanSpinner    animated fan disc
"""
from __future__ import annotations

import colorsys
import math

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static
from rich.style import Style
from rich.text import Text

from client import PredatorSenseClient, KeyboardLayout, frame_to_rgb
from tui_common import parse_color


# --------------------------------------------------------- neon gradient

# Magenta -> cyan, the Neon Predator signature sweep.
NEON_START = "#ff2e97"
NEON_END   = "#00e5ff"

# Embedded "VENATOR" wordmark in the ANSI-Shadow figlet style. Shipped
# as a constant so the banner looks right with zero extra dependency
# (pyfiglet is optional — see NeonBanner). Box-drawing only, so it
# renders identically on any UTF-8 terminal.
BANNER_VENATOR = (
    "██╗   ██╗███████╗███╗   ██╗ █████╗ ████████╗ ██████╗ ██████╗ \n"
    "██║   ██║██╔════╝████╗  ██║██╔══██╗╚══██╔══╝██╔═══██╗██╔══██╗\n"
    "██║   ██║█████╗  ██╔██╗ ██║███████║   ██║   ██║   ██║██████╔╝\n"
    "╚██╗ ██╔╝██╔══╝  ██║╚██╗██║██╔══██║   ██║   ██║   ██║██╔══██╗\n"
    " ╚████╔╝ ███████╗██║ ╚████║██║  ██║   ██║   ╚██████╔╝██║  ██║\n"
    "  ╚═══╝  ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝"
)


def _lerp_hex(a: str, b: str, t: float) -> str:
    """Linear-interpolate two #rrggbb colours. t clamps to [0, 1]."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return (f"#{round(ar + (br - ar) * t):02x}"
            f"{round(ag + (bg - ag) * t):02x}"
            f"{round(ab + (bb - ab) * t):02x}")


def gradient_text(s: str, start: str = NEON_START, end: str = NEON_END,
                  *, width: int | None = None, phase: float | None = None) -> Text:
    """Return a Rich Text with a horizontal `start`->`end` gradient.

    Multi-line aware: the colour tracks the *column*, normalised to the
    widest line, so the band stays vertical across every row of a figlet
    banner. Spaces are emitted uncoloured (cheaper, and invisible anyway).

    When `phase` (0..1) is given, a moving white specular highlight is
    swept across the fixed gradient — NeonBanner uses it to shimmer
    without losing the magenta->cyan identity.
    """
    out = Text()
    cols = width or max((len(ln) for ln in s.splitlines()), default=1)
    span = max(1, cols - 1)
    lines = s.splitlines()
    for li, line in enumerate(lines):
        for i, ch in enumerate(line):
            if ch == " ":
                out.append(" ")
                continue
            colour = _lerp_hex(start, end, i / span)
            if phase is not None:
                d = abs(i / span - phase)
                d = min(d, 1.0 - d)             # wrap the sweep at the edges
                hi = max(0.0, 1.0 - d / 0.14)   # narrow highlight band
                if hi:
                    colour = _lerp_hex(colour, "#ffffff", hi * 0.55)
            out.append(ch, style=Style(color=colour))
        if li != len(lines) - 1:
            out.append("\n")
    return out


# --------------------------------------------------------- colour maths

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    clamp = lambda v: max(0, min(255, int(v)))
    return f"#{clamp(r):02x}{clamp(g):02x}{clamp(b):02x}"


def hsv_to_hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return rgb_to_hex(round(r * 255), round(g * 255), round(b * 255))


# --------------------------------------------------------------- Slider

class Slider(Static, can_focus=True):
    """A horizontal click/keyboard slider. Posts `Slider.Changed` on every
    value change. The consumer decides what to do (apply, debounce, …)."""

    class Changed(Message):
        def __init__(self, slider: "Slider", value: int) -> None:
            self.slider = slider
            self.value = value
            super().__init__()

    BINDINGS = [
        Binding("left",  "dec",  "−", show=False),
        Binding("right", "inc",  "+", show=False),
        Binding("home",  "to_min", "", show=False),
        Binding("end",   "to_max", "", show=False),
    ]
    DEFAULT_CSS = """
    Slider { height: 1; width: 1fr; }
    Slider:focus { text-style: bold; }
    """
    value = reactive(0)

    def __init__(self, value: int = 0, *, min: int = 0, max: int = 255,
                 step: int = 5, id=None, classes=None):
        super().__init__(id=id, classes=classes)
        self._min, self._max, self._step = min, max, step
        # Clamp without the builtins (the params shadow them here).
        v = self._min if value < self._min else self._max if value > self._max else value
        # Seed without firing the watcher (widget isn't mounted yet).
        self.set_reactive(Slider.value, v)

    def watch_value(self, _old: int, new: int) -> None:
        self.refresh()
        if self.is_mounted:
            self.post_message(self.Changed(self, int(new)))

    def _track_width(self) -> int:
        return max(8, (self.size.width or 24) - 7)

    def render(self) -> Text:
        track = self._track_width()
        span = max(1, self._max - self._min)
        pos = round((self.value - self._min) / span * (track - 1))
        out = Text()
        for i in range(track):
            if i == pos:
                out.append("●", style=Style(color="#ff2e97", bold=True))
            elif i < pos:
                out.append("━", style=Style(color="#ff2e97"))
            else:
                out.append("─", style=Style(color="#5a4a72"))
        out.append(f" {self.value:>4}", style=Style(color="#f5e8ff", bold=True))
        return out

    def on_click(self, event) -> None:
        x = getattr(event, "x", 0) or 0
        track = self._track_width()
        frac = max(0, min(track - 1, x)) / max(1, track - 1)
        self.value = round(self._min + frac * (self._max - self._min))

    def action_dec(self):    self.value = max(self._min, self.value - self._step)
    def action_inc(self):    self.value = min(self._max, self.value + self._step)
    def action_to_min(self): self.value = self._min
    def action_to_max(self): self.value = self._max


# ------------------------------------------------------------ ColorWheel

class ColorWheel(Static, can_focus=True):
    """A clickable HSV colour wheel: angle = hue, radius = saturation.
    Brightness (value) is driven externally via `set_value`. Posts
    `ColorWheel.Picked(hex)` when the user clicks inside the disc."""

    class Picked(Message):
        def __init__(self, wheel: "ColorWheel", hex: str) -> None:
            self.wheel = wheel
            self.hex = hex
            super().__init__()

    WIDTH = 25
    HEIGHT = 11
    ASPECT = 2.0
    DEFAULT_CSS = """
    ColorWheel { width: 25; height: 11; }
    """
    value = reactive(1.0)

    def __init__(self, *, id=None):
        super().__init__(id=id)
        self._hue = 0.0
        self._sat = 0.0
        self._sel: tuple[int, int] | None = None

    def set_value(self, v: float) -> None:
        self.value = max(0.0, min(1.0, v))

    def watch_value(self, _old, _new) -> None:
        self.refresh()

    def current_hex(self) -> str:
        return hsv_to_hex(self._hue, self._sat, self.value)

    def _geom(self):
        cx = (self.WIDTH - 1) / 2.0
        cy = (self.HEIGHT - 1) / 2.0
        r_max = min(cx, cy * self.ASPECT)
        return cx, cy, r_max

    def render(self) -> Text:
        cx, cy, r_max = self._geom()
        out = Text()
        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                dx = x - cx
                dy = (y - cy) * self.ASPECT
                r = math.hypot(dx, dy)
                if r > r_max + 0.5:
                    out.append(" ")
                    continue
                hue = (math.atan2(dy, dx) % (2 * math.pi)) / (2 * math.pi)
                sat = min(1.0, r / r_max)
                hexc = hsv_to_hex(hue, sat, self.value)
                if self._sel == (x, y):
                    out.append("◎", style=Style(color="#000000", bgcolor=hexc, bold=True))
                else:
                    out.append("█", style=Style(color=hexc))
            if y != self.HEIGHT - 1: out.append("\n")
        return out

    def on_click(self, event) -> None:
        cx, cy, r_max = self._geom()
        x = getattr(event, "x", None)
        y = getattr(event, "y", None)
        if x is None or y is None:
            return
        dx = x - cx
        dy = (y - cy) * self.ASPECT
        r = math.hypot(dx, dy)
        if r > r_max + 0.5:
            return
        self._hue = (math.atan2(dy, dx) % (2 * math.pi)) / (2 * math.pi)
        self._sat = min(1.0, r / r_max)
        self._sel = (x, y)
        self.refresh()
        self.post_message(self.Picked(self, self.current_hex()))


# ----------------------------------------------------------- NeonBanner

class NeonBanner(Static):
    """Big gradient wordmark for the Home tab.

    Defaults to the embedded ANSI-Shadow "VENATOR" art (no dependency).
    Any other `text` uses pyfiglet when it's installed, else degrades to
    a plain bold gradient of the word so the TUI always runs.
    """
    # Specular sweep: ~0.18 passes/sec at 12 fps. Slow + cheap (~6 lines
    # of figlet) so it reads as a gloss travelling across the wordmark,
    # not a strobe.
    SHIMMER_HZ = 8
    SHIMMER_SPEED = 0.18

    def __init__(self, text: str = "VENATOR", subtitle: str = "", *, id=None):
        super().__init__(id=id)
        self._text = text
        self._subtitle = subtitle
        self._phase = None   # None on the first paint -> clean linear gradient

    def on_mount(self) -> None:
        self.set_interval(1.0 / self.SHIMMER_HZ, self._tick)

    def _tick(self) -> None:
        # Don't animate (or wake the compositor) while we're on a hidden tab:
        # a widget in an inactive TabPane has zero layout area.
        if self.size.area == 0:
            return
        import time
        self._phase = (time.monotonic() * self.SHIMMER_SPEED) % 1.0
        self.refresh()

    def _art(self) -> str:
        if self._text.upper() == "VENATOR":
            return BANNER_VENATOR
        try:
            from pyfiglet import Figlet
            return Figlet(font="ansi_shadow", width=200).renderText(
                self._text).rstrip("\n")
        except Exception:
            return self._text

    def render(self) -> Text:
        banner = gradient_text(self._art(), phase=self._phase)
        if self._subtitle:
            banner.append("\n")
            banner.append(self._subtitle,
                          style=Style(italic=True, color="#b388ff"))
        return banner


# ------------------------------------------------------------------ Panel

class Panel(Vertical):
    """A titled, heavy-bordered card — the Home-dashboard look, reusable
    as a section container in any tab.

    `variant` picks the accent: magenta (default), cyan, amber, green.
    Styling lives in tui.tcss under `.panel` / `.panel-<variant>`.
    """
    def __init__(self, *children, title: str = "", variant: str = "magenta",
                 classes: str = "", **kwargs):
        cls = f"panel panel-{variant} {classes}".strip()
        super().__init__(*children, classes=cls, **kwargs)
        self._panel_title = title

    def on_mount(self) -> None:
        self.border_title = self._panel_title


# ------------------------------------------------------------- InfoButton

class InfoButton(Static):
    """A small 'ⓘ info' button that toggles an inline description box.

    Replaces always-on muted help text: the explanation is one click away
    but the panel stays clean and uncramped until the user wants it.
    """
    DEFAULT_CSS = """
    InfoButton { height: auto; }
    InfoButton > #info_text {
        display: none; height: auto; width: 1fr;
        padding: 0 1; margin: 1 0 0 0;
        color: $text-muted; background: $surface;
        border-left: thick $secondary;
    }
    InfoButton.-open > #info_text { display: block; }
    """

    def __init__(self, text: str, *, id=None):
        super().__init__(id=id)
        self._text = text

    def compose(self) -> ComposeResult:
        yield Button("info ▾", id="info_btn", classes="info-btn")
        yield Static(self._text, id="info_text")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "info_btn":
            self.toggle_class("-open")
            event.button.label = "info ▴" if self.has_class("-open") else "info ▾"
            event.stop()


# ------------------------------------------------------------- ColorPopup

class ColorPopup(ModalScreen[str | None]):
    """Modal colour picker. Returns normalised `#rrggbb` (or None).

    Inputs, all kept in sync and live-previewed by the swatch:
      * an HSV colour wheel (angle=hue, radius=saturation) + a brightness
        (value) slider
      * a hex field and three R/G/B fields
      * a quick palette + recent colours
    """
    PALETTE = ["#ff0000", "#ff6a00", "#ffd400", "#00ff66",
               "#00e5ff", "#2e6bff", "#ff2e97", "#ffffff"]
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    DEFAULT_CSS = """
    ColorPopup { align: center middle; }
    ColorPopup > #popup {
        background: $surface; border: thick $primary;
        padding: 1 2; width: 74; height: auto;
    }
    ColorPopup #wheel_row { height: auto; }
    ColorPopup #wheel_side { width: 1fr; height: auto; padding-left: 2; }
    ColorPopup #swatch {
        height: 3; border: tall $panel;
        content-align: center middle; margin-bottom: 1;
    }
    ColorPopup .field { height: 3; }
    ColorPopup .field Label { width: 5; padding: 1 1 0 0; color: $text-muted; }
    ColorPopup #popup_input { width: 1fr; }
    ColorPopup .rgb Input { width: 8; margin-right: 1; }
    ColorPopup .valrow { height: 1; margin: 1 0; }
    ColorPopup .valrow Label { width: 8; padding: 0 1 0 0; color: $text-muted; }
    ColorPopup .valrow Slider { width: 1fr; }
    ColorPopup .chip-row { height: 3; padding: 0; }
    ColorPopup .btn-row { height: auto; padding-top: 1; }
    """

    def __init__(self, initial: str = "#ff0000", *,
                 recents: list[str] | None = None,
                 title: str = "Pick a colour"):
        super().__init__()
        self._initial = parse_color(initial) or "#ff0000"
        self._title   = title
        self._recents = list(recents or [])
        self._sync    = False    # guard against input<->wheel feedback loops

    def compose(self) -> ComposeResult:
        r, g, b = hex_to_rgb(self._initial)
        with Vertical(id="popup"):
            yield Static(f"[b]{self._title}[/]")
            with Horizontal(id="wheel_row"):
                yield ColorWheel(id="wheel")
                with Vertical(id="wheel_side"):
                    yield Static("", id="swatch")
                    with Horizontal(classes="field"):
                        yield Label("Hex")
                        yield Input(value=self._initial, id="popup_input",
                                    placeholder="#ff00aa")
                    with Horizontal(classes="field rgb"):
                        yield Label("RGB")
                        yield Input(value=str(r), id="in_r", placeholder="R")
                        yield Input(value=str(g), id="in_g", placeholder="G")
                        yield Input(value=str(b), id="in_b", placeholder="B")
            with Horizontal(classes="valrow"):
                yield Label("Bright")
                yield Slider(100, min=0, max=100, step=5, id="val_slider")
            yield Static("[dim]quick[/]")
            with Horizontal(classes="chip-row"):
                for hexv in self.PALETTE:
                    yield Button(" ", id=f"pal_{hexv.lstrip('#')}", classes="chip")
            if self._recents:
                yield Static("[dim]recent[/]")
                with Horizontal(classes="chip-row"):
                    for hexv in self._recents:
                        yield Button(" ", id=f"rec_{hexv.lstrip('#')}", classes="chip")
            with Horizontal(classes="btn-row"):
                yield Button("Apply",  id="popup_ok",     variant="primary")
                yield Button("Cancel", id="popup_cancel")

    def on_mount(self) -> None:
        self._paint_chips()
        self._set_color(self._initial, src="init")
        self.set_focus(self.query_one("#popup_input", Input))

    def _paint_chips(self) -> None:
        for chip in self.query(".chip").results(Button):
            cid = chip.id or ""
            if "_" in cid:
                chip.styles.background = "#" + cid.split("_", 1)[1]

    def _set_color(self, hexv: str, *, src: str) -> None:
        """Single sync point. Update every widget except the one that
        originated the change, guarded so we never recurse."""
        norm = parse_color(hexv)
        if not norm:
            return
        self._sync = True
        try:
            sw = self.query_one("#swatch", Static)
            sw.styles.background = norm
            sw.update(f"[b]{norm}[/]")
            if src != "hex":
                self.query_one("#popup_input", Input).value = norm
            if src != "rgb":
                r, g, b = hex_to_rgb(norm)
                self.query_one("#in_r", Input).value = str(r)
                self.query_one("#in_g", Input).value = str(g)
                self.query_one("#in_b", Input).value = str(b)
        finally:
            self._sync = False

    def on_color_wheel_picked(self, event: ColorWheel.Picked) -> None:
        self._set_color(event.hex, src="wheel")

    def on_slider_changed(self, event: Slider.Changed) -> None:
        if event.slider.id == "val_slider":
            wheel = self.query_one("#wheel", ColorWheel)
            wheel.set_value(event.value / 100)
            self._set_color(wheel.current_hex(), src="wheel")

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._sync:
            return
        if event.input.id == "popup_input":
            norm = parse_color(event.value)
            if norm:
                self._set_color(norm, src="hex")
        elif event.input.id in ("in_r", "in_g", "in_b"):
            try:
                r = int(self.query_one("#in_r", Input).value or 0)
                g = int(self.query_one("#in_g", Input).value or 0)
                b = int(self.query_one("#in_b", Input).value or 0)
            except ValueError:
                return
            self._set_color(rgb_to_hex(r, g, b), src="rgb")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "popup_ok":
            self._apply()
        elif bid == "popup_cancel":
            self.dismiss(None)
        elif bid.startswith(("pal_", "rec_")):
            self._set_color("#" + bid.split("_", 1)[1], src="chip")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._apply()

    def _apply(self) -> None:
        norm = parse_color(self.query_one("#popup_input", Input).value)
        if norm is None:
            self.app.notify("Invalid colour", severity="error", timeout=3)
            return
        self.dismiss(norm)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------- KeyboardView

class KeyboardView(Static):
    """Renders the 22x6 matrix of keyboard cells with live LED colours.

    Each cell is one Rich span tagged with `@click` meta — Textual
    dispatches the click to `App.action_cell_clicked(cell)` with the
    exact cell index of the character the user clicked. No coord math,
    no off-by-one from padding. Cells with no mapped key are rendered
    as blank gaps (so the preview looks like a sparse keyboard, not a
    grid of dots).
    """
    POLL_INTERVAL_S = 0.5
    CELL_WIDTH = 5

    selected = reactive(None, layout=False)
    frame_rgb: reactive[list] = reactive(list)

    def __init__(self, client: PredatorSenseClient, layout: KeyboardLayout,
                 *, id=None):
        super().__init__(id=id)
        self.client = client
        # NB: Widget already defines a read-only `layout` property
        # (controls vertical/horizontal child layout). Don't shadow it.
        self.kbd_layout = layout
        self.frame_rgb = [(0, 0, 0)] * layout.num_cells
        self._last_key = None   # (raw frame bytes, brightness) of the last paint

    def on_mount(self) -> None:
        self.set_interval(self.POLL_INTERVAL_S, self._poll)
        self._poll()

    def on_resize(self, event=None) -> None:
        # Becoming visible (hidden tab -> shown) resizes us from 0 area.
        # Force the next poll to repaint with fresh data promptly.
        self._last_key = None

    def _poll(self) -> None:
        # Skip entirely while on a hidden tab (zero layout area): no sysfs
        # read, no rebuild, no repaint. Resumes on tab switch via on_resize.
        if self.size.area == 0:
            return
        raw = self.client.get_frame()
        bright = max(0, min(255, self.client.get_brightness()))
        # Nothing changed since the last paint? Then the 132-cell rebuild +
        # refresh() would be wasted work — the common idle case (static
        # keyboard, no animation running). Bail before touching anything.
        key = (raw, bright)
        if key == self._last_key:
            return
        self._last_key = key
        rgb = frame_to_rgb(raw, self.kbd_layout.num_cells)
        scale = bright / 255.0 if bright > 0 else 1.0
        rgb = [(int(r * scale), int(g * scale), int(b * scale)) for r, g, b in rgb]
        self.frame_rgb = rgb
        self.refresh()

    def render(self) -> Text:
        text = Text()
        cw = self.CELL_WIDTH
        content_w = cw - 1
        for row in range(self.kbd_layout.ROWS):
            for col in range(self.kbd_layout.num_cols):
                cell = self.kbd_layout.cell_of(col, row)
                name = (
                    self.kbd_layout.cell_to_name.get(cell)
                    if cell is not None else None
                )
                if not name:
                    text.append(" " * cw)
                    continue
                label = name[:content_w].center(content_w)
                r, g, b = (
                    self.frame_rgb[cell]
                    if cell < len(self.frame_rgb) else (0, 0, 0)
                )
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                fg = "white" if lum < 128 else "black"
                bg = f"rgb({r},{g},{b})"
                # NB: don't attach `meta={...}` here — Textual 5.x's Strip
                # renderer crashes when it tries to deserialize style meta
                # ("bad marshal data"), which kills the paint and leaves a
                # black screen. Click hit-test goes through on_click()
                # below using event coords.
                style = Style(color=fg, bgcolor=bg)
                if self.selected == cell:
                    style += Style(bold=True, reverse=True)
                text.append(label, style=style)
                text.append(" ")
            text.append("\n")
        return text

    def on_click(self, event) -> None:
        # event.x / event.y are widget-local content offsets (Textual
        # excludes borders + padding for us when both are zero on this
        # widget). Each cell is CELL_WIDTH chars wide on screen, each
        # row is 1 char tall.
        x = getattr(event, "x", None)
        y = getattr(event, "y", None)
        if x is None or y is None:
            return
        col = x // self.CELL_WIDTH
        row = y
        cell = self.kbd_layout.cell_of(col, row)
        if cell is None:
            return
        name = self.kbd_layout.cell_to_name.get(cell)
        if not name:
            return
        self.selected = cell
        # Hand off to the App so it can update the Paint tab UI.
        if hasattr(self.app, "action_cell_clicked"):
            self.app.action_cell_clicked(cell)


# ------------------------------------------------------------------ status bar

class StatusBar(Static):
    """Shows current mode / colour / brightness / running scheme."""

    def __init__(self, client: PredatorSenseClient, *, id=None):
        super().__init__(id=id)
        self.client = client
        self._last = None

    def on_mount(self) -> None:
        self.set_interval(0.5, self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        # Skip while on a hidden tab.
        if self.size.area == 0:
            return
        try:
            mode = self.client.get_mode() or "?"
            color = self.client.get_color() or "—"
            bright = self.client.get_brightness()
            dev = self.client.device_name()
        except Exception as e:
            self.update(f"[bold red]error:[/] {e}")
            return
        markup = (
            f"[b]{dev}[/]   mode=[cyan]{mode}[/]  colour=[magenta]{color}[/]  "
            f"brightness=[yellow]{bright}[/]/255"
        )
        # Only repaint when something actually changed.
        if markup == self._last:
            return
        self._last = markup
        self.update(markup)


# -------------------------------------------------------------- ButtonGrid

class ButtonGrid(ScrollableContainer):
    """A grid container that reflows its column count on resize.

    Textual's grid layout doesn't have CSS flex-wrap. We approximate it
    by recomputing `grid-size-columns` from the container width every
    time the widget resizes.
    """
    DEFAULT_CSS = """
    ButtonGrid {
        layout: grid;
        grid-gutter: 1 1;
        grid-size: 3;
        height: 1fr;
        padding: 0 1;
    }
    ButtonGrid Button {
        width: 100%;
        margin: 0;
        min-width: 0;
    }
    """
    MIN_CELL_WIDTH = 18

    def on_resize(self) -> None:
        w = max(1, self.size.width - 2)  # padding budget
        cols = max(1, w // self.MIN_CELL_WIDTH)
        # styles.grid_size_columns expects an int
        self.styles.grid_size_columns = cols


# ------------------------------------------------------------- FanSpinner

class FanSpinner(Static):
    """A rotating fan disc rendered as a coloured-cell pie.

    Each character is one full ``█`` block; the cell's foreground
    colour picks which wedge it belongs to. Earlier rev used Unicode
    half-blocks for sub-pixel Y-resolution, but that came with two
    visible problems on a real terminal:

    1. The half-block edges shimmered between frames (every refresh
       toggled which sub-pixel of a boundary cell got the new wedge
       colour). Full blocks have no sub-pixel ambiguity → no shimmer.
    2. With 7 thin wedges + only ~7 cells of radius, three blades
       always blended together in the centre and the eye gave up.

    Now: 5 wedges at 72° each, with aspect-corrected geometry so each
    wedge is clearly visible even at the smaller radius. Rotation is
    capped below Nyquist for the wedge count + frame rate so the eye
    can always follow a single blade around the disc.
    """
    WIDTH    = 23
    HEIGHT   = 11
    BLADES   = 6           # MUST be even — see note below
    REFRESH_HZ = 8         # 125 ms per frame; smooth enough, ~20% less CPU

    # MUST be even. With an odd blade count the alternating
    # light/dark scheme places two same-coloured wedges next to each
    # other at the 360°/0° wraparound, merging visually into one
    # bigger region. (e.g., BLADES=5 reads as "3-4 visible blades"
    # because slices 0+4 fuse.) 6 gives clean 60° wedges and clear
    # alternation all the way around the disc.

    # Cap visible rotation to below Nyquist for the wedge count +
    # frame rate so we don't get wagon-wheel aliasing. With 6 blades
    # at 10 Hz, each blade pass needs ≥2 frames to track cleanly →
    # max safe rate = 2π / (6 * 2 * 0.1) ≈ 5.2 rad/s.
    VISIBLE_RATE_MAX = 5.0   # rad/s
    # Scale rpm -> rad/s. We *want* low rpms (~1000) to still be
    # visibly rotating; high rpms (~6000) cap out at VISIBLE_RATE_MAX.
    # The constant below makes 1000 rpm ≈ 1 rad/s, 5000 ≈ 5 rad/s.
    RPM_SCALE = 1000.0

    rpm     = reactive(0,        layout=False)
    label   = reactive("fan",    layout=False)
    descr   = reactive("",       layout=False)

    DEFAULT_CSS = """
    FanSpinner {
        width: 26;
        height: auto;
        padding: 0 1;
    }
    """

    # Two strong, theme-independent shades so the wedge pattern reads
    # against any background (light/dark). White-ish + dim cyan-ish
    # gives the high contrast needed for the rotation to be obvious;
    # using exact `bright_*` ANSI names keeps it portable.
    BLADE_LIGHT = "rgb(220,240,255)"
    BLADE_DARK  = "rgb(20,90,140)"
    HUB         = "rgb(255,200,40)"

    def __init__(self, label: str, descr: str = "", *, id=None):
        super().__init__(id=id)
        self.label = label
        self.descr = descr
        self._phase = 0.0
        self._last_tick_ts = None

    def on_mount(self) -> None:
        self.set_interval(1.0 / self.REFRESH_HZ, self._tick)

    def _tick(self) -> None:
        # Don't spin (or wake the compositor) while off-screen: a widget on
        # a hidden tab has zero layout area. This stops the two spinners on
        # the Power tab from rendering when you're looking at another tab.
        if self.size.area == 0:
            self._last_tick_ts = None
            return
        import time as _t
        now = _t.monotonic()
        if self._last_tick_ts is None:
            self._last_tick_ts = now
            return
        dt = now - self._last_tick_ts
        self._last_tick_ts = now
        # Clamp dt — if a frame is delayed (UI churn elsewhere) we
        # don't want the next frame to leap a quarter-turn.
        dt = max(0.04, min(dt, 0.2))
        if self.rpm <= 0:
            return
        import math as _math
        visible_rate = min(self.rpm / self.RPM_SCALE, self.VISIBLE_RATE_MAX)
        self._phase = (self._phase + dt * visible_rate) % (2 * _math.pi)
        self.refresh()

    def render(self) -> Text:
        import math as _math
        out = Text()
        out.append(f" {self.label}  ", style=Style(bold=True))
        out.append(f"{self.rpm:>5d} rpm\n",
                   style=Style(color="yellow", bold=True))
        if self.descr:
            out.append(f" {self.descr}\n", style=Style(dim=True))
        cx = (self.WIDTH  - 1) / 2.0
        cy = (self.HEIGHT - 1) / 2.0
        # Terminal cells are ~2x taller than wide on most fonts, so
        # scale dy by 2 to get a circle, not an oval.
        ASPECT = 2.0
        r_max = min(cx, cy * ASPECT) - 0.3
        r_hub = 1.0
        slice_size = (2 * _math.pi) / self.BLADES

        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                dx = x - cx
                dy = (y - cy) * ASPECT
                r = _math.hypot(dx, dy)
                if r > r_max:
                    out.append(" ")
                    continue
                if r < r_hub:
                    out.append("█", style=Style(color=self.HUB))
                    continue
                angle = (_math.atan2(dy, dx) + self._phase) % (2 * _math.pi)
                slice_idx = int(angle / slice_size)
                colour = (self.BLADE_LIGHT if slice_idx % 2 == 0
                          else self.BLADE_DARK)
                out.append("█", style=Style(color=colour))
            out.append("\n")
        return out
