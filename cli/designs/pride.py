# SPDX-License-Identifier: GPL-2.0-only
"""Six-stripe pride flag across the 128 cells."""

NAME = "pride"
DESCRIPTION = "Six-stripe pride flag across the cell array"

STRIPES = [
    (228,   3,   3),   # red
    (255, 140,   0),   # orange
    (255, 237,   0),   # yellow
    (  0, 128,  38),   # green
    (  0,  77, 255),   # blue
    (117,   7, 135),   # purple
]


def render(t, num_cells, keymap):
    buf = bytearray(num_cells * 3)
    per = num_cells / len(STRIPES)
    for i in range(num_cells):
        idx = min(int(i / per), len(STRIPES) - 1)
        r, g, b = STRIPES[idx]
        buf[i * 3 + 0] = r
        buf[i * 3 + 1] = g
        buf[i * 3 + 2] = b
    return bytes(buf)
