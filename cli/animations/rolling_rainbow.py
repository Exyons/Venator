# SPDX-License-Identifier: GPL-2.0-only
"""Hue cycles across cells over time. Cell index acts as a phase offset."""

import colorsys

NAME = "rolling_rainbow"
DESCRIPTION = "Hue cycles across cells over time"
FPS = 30

SPEED  = 0.30   # full hue cycles per second
SPREAD = 1.00   # how many full rainbows fit across the cell array


def render(t, num_cells, keymap):
    buf = bytearray(num_cells * 3)
    for i in range(num_cells):
        hue = (t * SPEED + (i / num_cells) * SPREAD) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        buf[i * 3 + 0] = int(r * 255)
        buf[i * 3 + 1] = int(g * 255)
        buf[i * 3 + 2] = int(b * 255)
    return bytes(buf)
