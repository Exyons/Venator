# SPDX-License-Identifier: GPL-2.0-only
"""Both keyboard and lightbar slowly rotate through the HSV hue
wheel together. Same hue at all times — much more "synchronised"
than running each side's own rainbow effect (which would drift).
"""

import colorsys

NAME = "rainbow_sync"
DESCRIPTION = "single hue cycling through the whole rainbow, " \
              "synchronised on keyboard and lightbar"
FPS = 6
PERIOD_S = 20.0   # one full hue rotation


def step(t: float) -> dict:
    hue = (t % PERIOD_S) / PERIOD_S
    r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
    hex_color = f"{r:02x}{g:02x}{b:02x}"
    return {
        "keyboard": {"mode": "static", "color": hex_color, "brightness": 220},
        "lightbar": {"mode": "static", "color": hex_color, "brightness": 220,
                     "speed": 5},
    }
