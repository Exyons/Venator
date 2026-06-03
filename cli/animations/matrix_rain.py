# SPDX-License-Identifier: GPL-2.0-only
"""Matrix-style green rain that *actually* falls down the keyboard columns.

The PH16-71 keyboard MCU addresses its 128 cells as a (col, row) matrix
with `cell = col * 6 + row_from_bottom`. So col_index = cell // 6 and
row_from_top = 5 - (cell % 6). With ROWS=6 and 22 logical columns this
matches the physical layout: row 5 is the function-key strip at the top,
row 0 is the modifier strip at the bottom.

Each column has its own drop. The drop's head is the bright white-green
leading edge; a fading green trail follows behind it. When the head
passes the bottom row by TRAIL_LENGTH cells, the drop is retired and a
new one spawns on that column after a short delay.

Independent of the keymap.json (which we don't strictly need here -- the
matrix structure is purely cell-arithmetic). Empty positions inside a
column (the gaps where wide keys span multiple cells) just stay dark
when the drop passes through them.
"""

import random

NAME = "matrix_rain"
DESCRIPTION = "Green rain pouring top-to-bottom along keyboard columns"
FPS = 20

ROWS = 6
DROP_SPEED   = 5.5    # rows per second
TRAIL_LENGTH = 4      # cells of trail behind the head
SPAWN_PROB   = 0.05   # per empty column per frame
HEAD_COLOR   = (180, 255, 180)
TRAIL_COLOR  = (  0, 220,   0)

_drops: dict[int, float] = {}   # col_idx -> head position (0 = top row, increasing downward)
_last_t: list[float | None] = [None]


def _column_layout(num_cells: int) -> list[list[int | None]]:
    """Group cell indices into columns, ordered top-to-bottom.

    cols[col][0] = cell at the TOP of that column (function-key row),
    cols[col][ROWS-1] = cell at the BOTTOM (modifier row). Empty slots
    are None when the cell index falls outside num_cells.
    """
    n_cols = (num_cells + ROWS - 1) // ROWS
    out: list[list[int | None]] = [[None] * ROWS for _ in range(n_cols)]
    for c in range(num_cells):
        col = c // ROWS
        row_from_bottom = c % ROWS
        row_from_top = (ROWS - 1) - row_from_bottom
        out[col][row_from_top] = c
    return out


def render(t, num_cells, keymap):
    buf = bytearray(num_cells * 3)
    cols = _column_layout(num_cells)
    n_cols = len(cols)

    # Frame delta. Reset cleanly if the animator was paused
    # (wake-on-keypress resume drops `last_tick` so `t` jumps forward).
    last = _last_t[0]
    dt = (t - last) if last is not None else 0.0
    _last_t[0] = t
    if dt < 0 or dt > 1.0:
        dt = 1.0 / FPS

    # Spawn new drops on idle columns.
    for col_idx in range(n_cols):
        if col_idx not in _drops and random.random() < SPAWN_PROB:
            # Start just above the top row so the head fades in cleanly.
            _drops[col_idx] = -1.0

    # Advance and render.
    retired: list[int] = []
    for col_idx, pos in list(_drops.items()):
        pos += DROP_SPEED * dt
        _drops[col_idx] = pos

        # head_row floor; head + trail occupy [head, head-TRAIL_LENGTH]
        head_row = int(pos)
        for i in range(TRAIL_LENGTH + 1):     # 0 = head, 1..N = trail
            row = head_row - i
            if not (0 <= row < ROWS):
                continue
            cell = cols[col_idx][row]
            if cell is None or not (0 <= cell < num_cells):
                continue
            if i == 0:
                r, g, b = HEAD_COLOR
            else:
                f = 1.0 - i / (TRAIL_LENGTH + 1)
                r = int(TRAIL_COLOR[0] * f)
                g = int(TRAIL_COLOR[1] * f)
                b = int(TRAIL_COLOR[2] * f)
            buf[cell * 3 + 0] = r
            buf[cell * 3 + 1] = g
            buf[cell * 3 + 2] = b

        # Retire once head + trail are entirely off the bottom edge.
        if pos - TRAIL_LENGTH > ROWS:
            retired.append(col_idx)
    for col_idx in retired:
        del _drops[col_idx]

    return bytes(buf)
