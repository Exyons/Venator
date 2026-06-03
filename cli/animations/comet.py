# SPDX-License-Identifier: GPL-2.0-only
"""Comet: a bright head with a fading trail moves through the cell array
and wraps around."""

NAME = "comet"
DESCRIPTION = "Bright head with a fading trail wraps around the cell array"
FPS = 30

SPEED = 30.0           # cells per second
TRAIL = 14             # trail length in cells
COLOR = (90, 200, 255) # cyan-ish


def render(t, num_cells, keymap):
    head = (t * SPEED) % num_cells
    buf = bytearray(num_cells * 3)
    for i in range(num_cells):
        # signed distance from head, wrapped
        d = (head - i) % num_cells
        if d < TRAIL:
            f = 1.0 - d / TRAIL
            f = f * f       # quadratic falloff; head pops more
            buf[i * 3 + 0] = int(COLOR[0] * f)
            buf[i * 3 + 1] = int(COLOR[1] * f)
            buf[i * 3 + 2] = int(COLOR[2] * f)
    return bytes(buf)
