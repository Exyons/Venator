# SPDX-License-Identifier: GPL-2.0-only
"""Firmware breathing effect, but with the colour smoothly rotating
on a slow HSV wheel. Lets the firmware handle the brightness fade
while we just swap colours every few seconds.
"""

import colorsys

NAME = "breathing_rotate"
DESCRIPTION = "firmware breathing fade + slow colour rotation"
FPS = 2                       # firmware does the fade — we just shift hue
PERIOD_S = 30.0


def step(t: float) -> dict:
    hue = (t % PERIOD_S) / PERIOD_S
    r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
    return {
        "mode":       "breathing",
        "speed":      5,
        "brightness": 200,
        "color":      f"{r:02x}{g:02x}{b:02x}",
    }
