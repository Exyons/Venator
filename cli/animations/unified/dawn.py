# SPDX-License-Identifier: GPL-2.0-only
"""Slow morning fade. Both keyboard and lightbar transition from
deep red → orange → yellow → soft white over PERIOD_S seconds, then
hold. Pleasant ambient effect.
"""

NAME = "dawn"
DESCRIPTION = "slow sunrise: deep red → soft white, in lockstep across both"
FPS = 2
PERIOD_S = 60.0   # one minute to fully rise; afterwards holds soft white


def _lerp_rgb(c1, c2, t: float):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# Keyframes: (offset_fraction, (R, G, B))
STOPS = [
    (0.00, (0x20, 0x00, 0x00)),  # deep red ember
    (0.30, (0xff, 0x40, 0x00)),  # bright orange
    (0.60, (0xff, 0xa0, 0x10)),  # warm amber
    (0.85, (0xff, 0xe0, 0x80)),  # gentle yellow
    (1.00, (0xff, 0xf0, 0xe0)),  # soft sunrise white
]


def step(t: float) -> dict:
    phase = min(t / PERIOD_S, 1.0)
    # Find the segment we're in.
    r = g = b = 0
    for (a_off, a_col), (b_off, b_col) in zip(STOPS, STOPS[1:]):
        if a_off <= phase <= b_off:
            local = (phase - a_off) / (b_off - a_off)
            r, g, b = _lerp_rgb(a_col, b_col, local)
            break
    else:
        r, g, b = STOPS[-1][1]
    hex_color = f"{r:02x}{g:02x}{b:02x}"
    bright = int(80 + 170 * phase)   # ramps 80..250 over the period
    return {
        "keyboard": {"mode": "static", "color": hex_color, "brightness": bright},
        "lightbar": {"mode": "static", "color": hex_color, "brightness": bright,
                     "speed": 5},
    }
