# SPDX-License-Identifier: GPL-2.0-only
"""Aurora borealis-inspired gradient: deep green -> bright green -> blue -> purple."""

NAME = "aurora"
DESCRIPTION = "Aurora borealis gradient (green / cyan / blue / purple)"

# (position_along_cells_0_to_1, (R, G, B))
STOPS = [
    (0.00, (  0,  60,  20)),
    (0.33, ( 30, 230, 130)),
    (0.66, ( 40, 130, 255)),
    (1.00, (130,  30, 220)),
]


def render(t, num_cells, keymap):
    buf = bytearray(num_cells * 3)
    last = max(1, num_cells - 1)
    for i in range(num_cells):
        f = i / last
        # find the segment f sits in
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
