# SPDX-License-Identifier: GPL-2.0-only
"""Both keyboard and lightbar pulse the same colour together, fading
in and out in lockstep. A "unified breathing" effect that matches
across the whole laptop.

Tweak COLOR / PERIOD_S to taste.
"""

import math

NAME = "color_pulse"
DESCRIPTION = "keyboard and lightbar pulse the same colour in lockstep"
FPS = 6
PERIOD_S = 4.0
COLOR = (0x40, 0x80, 0xff)   # cool blue


def step(t: float) -> dict:
    # Sine wave from 0..1 across PERIOD_S.
    phase = (t % PERIOD_S) / PERIOD_S
    intensity = (math.sin(phase * 2 * math.pi - math.pi / 2) + 1) / 2
    r = int(COLOR[0] * intensity)
    g = int(COLOR[1] * intensity)
    b = int(COLOR[2] * intensity)
    hex_color = f"{r:02x}{g:02x}{b:02x}"
    bright = int(50 + 200 * intensity)   # 50..250
    return {
        "keyboard": {"mode": "static", "color": hex_color, "brightness": bright},
        "lightbar": {"mode": "static", "color": hex_color, "brightness": bright,
                     "speed": 5},
    }
