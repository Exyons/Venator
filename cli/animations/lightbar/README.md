# Lightbar animations

Drop-in Python modules. Each one defines:

```python
NAME = "your_name"
DESCRIPTION = "what it does"
FPS = 10                      # rewrites per second; 1..30 typical

def step(t: float) -> dict:
    """Return the lightbar state for time t (seconds since start).

    Returned dict accepts any subset of these keys; missing keys keep
    the current value:
       mode:       firmware mode name (off / breathing / neon / rainbow
                   / wave / ripple / scanner / strobe / static)
       brightness: 0..255
       speed:      0..255  (most modes ignore; useful for animated)
       color:      "RRGGBB" hex string — applied as the single colour
    """
```

Note: PH16-71's firmware doesn't expose per-zone colour control via
the WMBH WMI interface we have access to. Animations can only set ONE
colour at a time for the whole strip.

Run them with:

```
venator lightbar anim rainbow_cycle              # by name
venator lightbar anim ~/my.py --timeout 60      # absolute path, 60s
```

The runner spawns a background process that writes to the kernel sysfs
at the requested FPS. On Ctrl-C / `venator lightbar off` /
`--timeout` expiry it cleanly stops and turns the bar off.
