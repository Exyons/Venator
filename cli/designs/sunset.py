# SPDX-License-Identifier: GPL-2.0-only
"""Sunset gradient: deep orange -> pink -> indigo across the cell array."""

NAME = "sunset"
DESCRIPTION = "Sunset gradient (orange / pink / indigo)"

STOPS = [
    (0.00, (255, 140,  40)),
    (0.50, (255,  70, 140)),
    (1.00, ( 70,  20, 130)),
]


def render(t, num_cells, keymap):
    buf = bytearray(num_cells * 3)
    last = max(1, num_cells - 1)
    for i in range(num_cells):
        f = i / last
        for s in range(len(STOPS) - 1):
            p0, c0 = STOPS[s]
            p1, c1 = STOPS[s + 1]
            if p0 <= f <= p1:
                u = (f - p0) / max(1e-9, (p1 - p0))
                buf[i * 3 + 0] = int(c0[0] * (1 - u) + c1[0] * u)
                buf[i * 3 + 1] = int(c0[1] * (1 - u) + c1[1] * u)
                buf[i * 3 + 2] = int(c0[2] * (1 - u) + c1[2] * u)
                break
    return bytes(buf)
