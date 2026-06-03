# SPDX-License-Identifier: GPL-2.0-only
"""WASD pulses bright, rest dim red. Demonstrates targeting named keys.

Requires a keymap with W, A, S, D mapped. Run `venator map discover`
first if you haven't already.
"""

import math

NAME = "wasd_pulse"
DESCRIPTION = "WASD pulses blue, rest dim red. Needs W/A/S/D in your keymap."
FPS = 30

WASD   = ("W", "A", "S", "D")
BASE   = (20, 0, 0)     # dim red on the rest
PULSE  = (0, 100, 255)  # bright blue when pulse is full
PERIOD = 1.0            # seconds per pulse cycle


def render(t, num_cells, keymap):
    pulse = (math.sin(t * 2 * math.pi / PERIOD) + 1) / 2   # 0..1
    buf = bytearray(BASE) * num_cells
    keys = keymap.get("keys", {})
    for name in WASD:
        # Tolerate case differences -- match what the user typed during discover.
        cell = keys.get(name)
        if cell is None:
            cell = next((c for k, c in keys.items() if k.lower() == name.lower()), None)
        if cell is None:
            continue
        i = int(cell)
        if 0 <= i < num_cells:
            buf[i * 3 + 0] = int(PULSE[0] * pulse)
            buf[i * 3 + 1] = int(PULSE[1] * pulse)
            buf[i * 3 + 2] = int(PULSE[2] * pulse)
    return bytes(buf)
