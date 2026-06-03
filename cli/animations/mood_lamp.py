# SPDX-License-Identifier: GPL-2.0-only
"""Mood lamp: every key the same colour, hue drifts very slowly through
the spectrum at low saturation (pastel)."""

import colorsys

NAME = "mood_lamp"
DESCRIPTION = "All keys same pastel colour; hue drifts slowly"
FPS = 10

CYCLE_PERIOD = 60.0   # seconds for one full hue cycle
SATURATION   = 0.55
VALUE        = 1.0


def render(t, num_cells, keymap):
    hue = (t / CYCLE_PERIOD) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, SATURATION, VALUE)
    return bytes([int(r * 255), int(g * 255), int(b * 255)]) * num_cells
