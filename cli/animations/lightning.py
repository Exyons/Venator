# SPDX-License-Identifier: GPL-2.0-only
"""Lightning: dim cool background with occasional bright flashes."""

import random

NAME = "lightning"
DESCRIPTION = "Dim cool background; occasional bright multi-key flashes"
FPS = 30

STRIKE_CHANCE = 0.06      # per frame, chance to spawn a new strike
STRIKE_CELLS  = (3, 12)   # how many cells light up per strike
STRIKE_FRAMES = (2, 6)    # how long a struck cell stays bright
BASE  = (5, 5, 18)
BOLT  = (235, 235, 255)

_active: list[list[int]] = []   # [cell_idx, remaining_frames]


def render(t, num_cells, keymap):
    if random.random() < STRIKE_CHANCE:
        k = random.randint(*STRIKE_CELLS)
        for c in random.sample(range(num_cells), k=min(k, num_cells)):
            _active.append([c, random.randint(*STRIKE_FRAMES)])

    buf = bytearray(BASE) * num_cells
    surviving: list[list[int]] = []
    for entry in _active:
        c, n = entry
        if n <= 0:
            continue
        buf[c * 3 + 0] = BOLT[0]
        buf[c * 3 + 1] = BOLT[1]
        buf[c * 3 + 2] = BOLT[2]
        entry[1] = n - 1
        if entry[1] > 0:
            surviving.append(entry)
    _active[:] = surviving
    return bytes(buf)
