# Designs

A **design** is a one-shot static layout for the per-key buffer. Unlike
an animation, render is called once when you `venator rgb design
<name>`; the keyboard then stays on that frame until you do something
else. Unlike a *profile* (which is a snapshot of any mode), a design
specifically composes the per-key buffer.

Designs live in two formats:

## JSON (declarative — easy to author)

```jsonc
{
  "name": "...",
  "description": "...",
  "base_color": "#RRGGBB",          // optional, default #000000
  "cells": { "5": "#RRGGBB", ... }, // optional, raw cell index -> colour
  "keys":  { "W": "#RRGGBB", ... }  // optional, name -> colour via keymap
}
```

Layering: `base_color` fills every cell, then `cells` overrides specific
cell indices, then `keys` overrides via the user's `keymap.json`. Keys
missing from the keymap get a one-line note and are silently skipped.

Run `venator map discover` first if you want named-key designs to
"hit" real keys; otherwise the design still applies (every key gets
`base_color`, named-key overrides become no-ops).

## Python (procedural — needs code, more flexible)

Same contract as animations:

```python
NAME = "..."
DESCRIPTION = "..."

def render(t, num_cells, keymap):
    """Return num_cells*3 bytes (RGB per cell). t is always 0 for
    designs; the parameter is kept so the same file format works for
    both animations and designs."""
    ...
```

Run with:

```
venator rgb design --list
venator rgb design pride
venator rgb design gaming --brightness 200
venator rgb design ~/my-design.json
```

## Shipped designs

| Name         | Type | Notes |
|--------------|------|-------|
| `pride`      | py   | Six-stripe pride flag across cells. Works without a keymap. |
| `cyberpunk`  | py   | Alternating neon pink + cyan blocks. Works without a keymap. |
| `aurora`     | py   | Green / cyan / blue / purple gradient. Works without a keymap. |
| `sunset`     | py   | Orange / pink / indigo gradient. Works without a keymap. |
| `gaming`     | json | WASD glow + weapon/number-row + Tab/Esc accents. **Needs a keymap.** |
| `coding`     | json | Function-row orange, bracket/symbol keys teal. **Needs a keymap.** |
| `navigation` | json | Warm-white base with cool blue on arrows + Pg/Home/End cluster. **Needs a keymap.** |

## User overrides

Drop `.py` or `.json` in `~/.config/venator/designs/`. Same name
as a shipped design wins.
