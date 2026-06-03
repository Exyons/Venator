# SPDX-License-Identifier: GPL-2.0-only
"""Alternating neon pink + electric cyan blocks across the cell array."""

NAME = "cyberpunk"
DESCRIPTION = "Alternating neon pink + cyan blocks"

PINK  = (255,  20, 147)
CYAN  = (  0, 255, 255)
BLOCK = 2     # cells per colour block


def render(t, num_cells, keymap):
    buf = bytearray(num_cells * 3)
    for i in range(num_cells):
        r, g, b = PINK if (i // BLOCK) % 2 == 0 else CYAN
        buf[i * 3 + 0] = r
        buf[i * 3 + 1] = g
        buf[i * 3 + 2] = b
    return bytes(buf)
