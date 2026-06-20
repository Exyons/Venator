#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Shared helpers + constants for the venator TUI.

Pure-Python; no Textual import here so it's cheap to pull into every
module. Colour parsing, the theme list, and the Home-tab tagline pool
all live here.
"""
from __future__ import annotations

import re

HEX_RE = re.compile(r"#?[0-9a-fA-F]{6}$")

# Our own neon theme (registered in tui.py) leads the cycle so 't'
# always returns home; Textual's built-ins follow for users who care.
THEMES = [
    "neon-venator",
    "textual-dark",
    "nord",
    "gruvbox",
    "tokyo-night",
    "dracula",
    "monokai",
    "catppuccin-mocha",
    "textual-light",
]


def _norm_hex(s: str) -> str | None:
    s = s.strip()
    m = HEX_RE.match(s)
    if not m:
        return None
    return "#" + s.lstrip("#").lower()


def parse_color(s: str) -> str | None:
    """Accept either `#rrggbb`, `rrggbb`, or `r,g,b` decimal triplets.

    Returns the normalised `#rrggbb` form or None on parse failure.
    """
    s = s.strip()
    if "," in s:
        try:
            parts = [int(p.strip()) for p in s.split(",")]
        except ValueError:
            return None
        if len(parts) != 3 or not all(0 <= p <= 255 for p in parts):
            return None
        return f"#{parts[0]:02x}{parts[1]:02x}{parts[2]:02x}"
    return _norm_hex(s)


# Catchy gamer-tagline pool for the Home tab. Picked deterministically
# from today's date so the tagline is stable for 24 h, then rotates at
# the local midnight rollover.
TAGLINES = [
    "Are you ready, player one?",
    "Tonight, the keyboard listens.",
    "Power on. Limits off.",
    "Frame-perfect or it didn't happen.",
    "Cooler than your last clutch.",
    "Glow harder.",
    "Built for ranked.",
    "Stay frosty.",
    "Don't blink.",
    "Boot it. Own it.",
    "Helios mode: engaged.",
    "Heat is hesitation.",
    "Set fans to legend.",
    "Some games deserve light.",
    "Latency is a state of mind.",
    "Press any key to ignite.",
    "Cap the battery. Uncap the rage.",
    "Render: maximum.",
    "RGB intensifies.",
    "Ascend, gamer.",
    "Quiet hands. Loud frames.",
    "Run the game, not the heat.",
    "EC says: I've seen things.",
    "Predator awake.",
]


def todays_tagline() -> str:
    """Pick a tagline that's stable for the calendar day. We hash the
    ISO date string so the same user sees the same line all day even
    if the TUI is reopened, and it rolls at midnight without us doing
    anything fancier than reading datetime.date.today().
    """
    import datetime
    import hashlib
    today = datetime.date.today().isoformat()
    h = int(hashlib.sha1(today.encode()).hexdigest(), 16)
    return TAGLINES[h % len(TAGLINES)]
