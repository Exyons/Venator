# Animations

Drop a `<name>.py` file in this directory or `~/.config/venator/animations/`
to create a custom animation. The CLI's `rgb animate <name>` will run it.

Each file must define:

```python
def render(t: float, num_cells: int, keymap: dict) -> bytes:
    """Return num_cells*3 bytes (RGB per cell) for the keyboard."""
```

Optional module-level attributes (all have defaults):

| name           | default | meaning                                 |
|----------------|---------|-----------------------------------------|
| `NAME`         | filename | human-readable name shown by `--list`  |
| `DESCRIPTION`  | `""`    | one-line description                    |
| `FPS`          | `30`    | tick rate; the CLI calls `render` this many times per second |

Arguments to `render`:

- `t` — seconds since the animation started (float).
- `num_cells` — 128 on PH16-71.
- `keymap` — the loaded `~/.config/venator/keymap.json`.
  `keymap["keys"]` maps key-name strings to cell indices; use it to
  highlight specific physical keys, e.g. `keymap["keys"].get("Esc")`.

The return value must be exactly `num_cells * 3` bytes. The CLI writes
the buffer to `/sys/class/predator/keyboard0/frame` and commits in one
transaction per tick.

## Examples shipped here

- `breathing.py` — solid orange fade in/out
- `gradient.py` — static red→blue gradient
- `rolling_rainbow.py` — hue rolls across cells over time
- `wasd_pulse.py` — WASD keys pulse blue, rest dim red. Demonstrates keymap usage.

## User overrides

If a user file in `~/.config/venator/animations/<name>.py` has
the same name as a shipped one, the user version wins.

## Running

```
venator rgb animate --list             # list available
venator rgb animate rolling_rainbow    # run by name
venator rgb animate ~/my-anim.py       # run from absolute path
venator rgb animate plasma --brightness 150
# Ctrl-C to stop. Keyboard stays on the last rendered frame; use
# `venator rgb static '#0000ff'` etc. to change it.
```
