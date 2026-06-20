# GUI

Frontends for the venator CLI. Both subprocess into
`venator` for mutations and read `/sys/class/predator/keyboard0/`
directly for the live preview, so the CLI stays canonical and the GUIs
don't duplicate its logic.

Currently shipping:

- **`venator tui`** — Textual terminal UI with a live keyboard
  preview, controls, effects, designs, animations, profiles, per-key
  painting, plus power/battery/thermal/lightbar/unified tabs. Works over
  SSH. Invoked as a subcommand of the main CLI (no separate binary).

## Install

The TUI is installed by `sudo make module-install` (or `hook-install` /
`manual-install`) alongside the CLI. Manual:

```bash
sudo dnf install python3-textual            # Fedora
sudo pacman -S python-textual               # Arch / CachyOS
# or: pip install --user textual

cd ~/Workspace/Venator
sudo make module-install
venator tui
```

## Module layout

The TUI is split into focused modules (all flat `.py` files in `gui/`
so the install glob picks them up):

```
tui.py             entry + assembly: PredatorSenseApp(mixins…, App),
                   central event dispatch, shared helpers, main()
tui_common.py      colour parsing, theme list, Home taglines
tui.tcss           the App-level CSS (loaded via PredatorSenseApp.CSS_PATH)
tui_widgets.py     ColorPopup, KeyboardView, StatusBar, ButtonGrid, FanSpinner
tui_tab_home.py        HomeTabMixin
tui_tab_keyboard.py    KeyboardTabMixin  (preview + effects/designs/anim/profiles/paint)
tui_tab_power.py       PowerTabMixin     (profile + AC/battery policy + fans/temps)
tui_tab_battery.py     BatteryTabMixin
tui_tab_lightbar.py    LightbarTabMixin
tui_tab_unified.py     UnifiedTabMixin
client.py          shared CLI/sysfs library (also used by future frontends)
```

Each tab is a **mixin** carrying its own `_compose_*`, `_refresh_*`, and
`_<tab>_handle_button` methods. `PredatorSenseApp` inherits all of them
plus `App`. Because Textual delivers each message type to a single
App-level handler, the central `on_button_pressed` in `tui.py` fans out
to each tab's `_<tab>_handle_button` in order; `on_input_changed` /
`on_list_view_selected` (keyboard) and `on_checkbox_changed` (power) are
unique to one mixin each, so they resolve directly via the MRO. To add a
tab: write a `FooTabMixin`, add it to the class bases and the `compose`
list, and give it a `_foo_handle_button` if it has buttons.

## Architecture

```
+-------------------------+
|  venator tui     |
|  (Textual, tui.py +     |
|   tui_* tab mixins)     |
+------------+------------+
             |
    +--------v--------+
    |   client.py     |    subprocess + sysfs
    |  (shared lib)   |
    +-----+------+----+
          |      |
sysfs reads      subprocess
    |                 |
/sys/class/      venator
predator/        (the CLI)
keyboard0/             |
                       v
                  /sys + kmod
```

`client.py` lives next to the frontend modules and is imported by
`tui.py` (and the tab mixins) directly when the CLI execs it. The CLI's
`tui` subcommand handles locating `tui.py` under
`/usr/local/share/venator/gui/` (or the source checkout) and
exec'ing python on it.

## Why subprocess and not "GUI writes /sys directly"?

The CLI is doing real work: auto-saving the `default` profile on every
change, spawning + tearing down the detached animator / keepalive
workers (which themselves read `/dev/input/event*-kbd` for wake-on-
keypress), translating mode names to EFF bytes, building per-key frames
with the right `{0x00, R, G, B}` cell padding, etc. The GUI side stays
fast by reading sysfs directly for the *preview* (live, no privilege
issue) and only shelling out for mutations.

Subprocess calls happen in a worker thread so the UI doesn't block.

## TUI keymap

The preview renders the 128-cell matrix as a 22-column × 6-row grid.
Cell positions are derived from `cell = col * 6 + row_from_bottom`
(regular matrix, no keymap lookup needed). Key *names* on each cell
come from `cli/keymaps/ph16-71.json` (or your
`~/.config/venator/keymap.json` if it exists). Matrix gaps where
wide keys span multiple cells render as blank — that's expected.
