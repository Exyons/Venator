# SPDX-License-Identifier: GPL-2.0-only
"""Plasma: three sine waves combined per cell, mapped to a purple/red palette."""

import math

NAME = "plasma"
DESCRIPTION = "Smooth sinusoidal plasma in purple/red"
FPS = 30

W1, W2, W3 = 8.0, 4.0, 6.0       # spatial frequencies
S1, S2, S3 = 2.0, 1.5, 0.30      # temporal speeds


def render(t, num_cells, keymap):
    buf = bytearray(num_cells * 3)
    for i in range(num_cells):
        x = i / num_cells
        v = (
            math.sin(x * W1 + t * S1) +
            math.sin(x * W2 + t * S2) +
            math.sin((x + t * S3) * W3)
        ) / 3.0
        v = (v + 1.0) * 0.5
        # palette: red-magenta-blue
        buf[i * 3 + 0] = int(255 * (0.6 + 0.4 * v))
        buf[i * 3 + 1] = int(30 * (1 - v))
        buf[i * 3 + 2] = int(255 * (1 - v) * 0.85)
    return bytes(buf)
