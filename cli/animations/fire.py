# SPDX-License-Identifier: GPL-2.0-only
"""Campfire flicker. Per-cell intensity decays each frame and is randomly
nudged up, then mapped to a fire palette (dark red -> orange -> yellow ->
white at the peaks).
"""

import random

NAME = "fire"
DESCRIPTION = "Campfire flicker; red/orange/yellow palette"
FPS = 30

_state = []


def _fire_color(v):
    v = max(0.0, min(1.0, v))
    if v > 0.85:
        # peak: yellow/white
        f = (v - 0.85) / 0.15
        return 255, 255, int(180 * f)
    if v > 0.55:
        # orange
        f = (v - 0.55) / 0.30
        return 255, int(80 + 175 * f), 0
    # base: dark red
    f = v / 0.55
    return int(40 + 215 * f), int(20 * f), 0


def render(t, num_cells, keymap):
    global _state
    if len(_state) != num_cells:
        _state = [random.random() * 0.5 for _ in range(num_cells)]
    buf = bytearray(num_cells * 3)
    for i in range(num_cells):
        _state[i] = _state[i] * 0.78 + random.random() * 0.35
        r, g, b = _fire_color(_state[i])
        buf[i * 3 + 0] = r
        buf[i * 3 + 1] = g
        buf[i * 3 + 2] = b
    return bytes(buf)
