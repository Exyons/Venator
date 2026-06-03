# SPDX-License-Identifier: GPL-2.0-only
"""Rotates the lightbar's global colour through the HSV wheel while
holding static mode. Slower than the firmware's built-in 'rainbow'
effect (which alternates per-zone) — this is a single smooth fade
across the whole strip.

Tweak PERIOD_S to slow / speed up the cycle.
"""

import colorsys

NAME = "rainbow_cycle"
DESCRIPTION = "smooth single-colour HSV fade across the whole bar"
FPS = 8                       # rewrites per second
PERIOD_S = 12.0               # seconds per full hue rotation


def step(t: float) -> dict:
    hue = (t % PERIOD_S) / PERIOD_S
    r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
    return {
        "mode":  "static",
        "color": f"{r:02x}{g:02x}{b:02x}",
    }
