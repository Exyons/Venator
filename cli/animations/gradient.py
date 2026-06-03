# SPDX-License-Identifier: GPL-2.0-only
"""Static gradient from COLOR_A to COLOR_B across the cell index space.

The cells don't map to physical keys in spatial order (the matrix is
scrambled), so this looks "random" until you've run map discover and
pull the cells back into spatial order with your own animation.
"""

NAME = "gradient"
DESCRIPTION = "Static R->B gradient across cell indices (not spatial)"
FPS = 1   # static, but tick once a second is safer than tick=0

COLOR_A = (255, 0, 0)    # cell 0
COLOR_B = (0, 0, 255)    # cell num_cells-1


def render(t, num_cells, keymap):
    buf = bytearray(num_cells * 3)
    last = max(1, num_cells - 1)
    for i in range(num_cells):
        f = i / last
        buf[i * 3 + 0] = int(COLOR_A[0] * (1 - f) + COLOR_B[0] * f)
        buf[i * 3 + 1] = int(COLOR_A[1] * (1 - f) + COLOR_B[1] * f)
        buf[i * 3 + 2] = int(COLOR_A[2] * (1 - f) + COLOR_B[2] * f)
    return bytes(buf)
