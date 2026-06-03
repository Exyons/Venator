# Unified animations

Animations that drive the **keyboard AND the rear lightbar** in
lockstep — same colour, same intensity, same phase at every
frame. Each animation is a Python module exporting:

```python
NAME = "your_name"
DESCRIPTION = "what it does"
FPS = 6           # frames per second; 1..15 recommended

def step(t: float) -> dict:
    """Return one frame of state at time t (seconds since start).

    Returned dict shape:
       {
         "keyboard": { "mode": "off|static|breathing|...",
                       "color":      "RRGGBB",
                       "brightness": 0..255 },
         "lightbar": { "mode": "off|breathing|...|static",
                       "color":      "RRGGBB",
                       "brightness": 0..255,
                       "speed":      0..255 },
       }

    Either half may be omitted to leave that side alone. Each frame
    is sent to the firmware via the same `set` atomic that the CLI
    uses, so colours change cleanly without flicker.
    """
```

## Shipped animations

| name           | what it does                                                |
|----------------|-------------------------------------------------------------|
| color_pulse    | both pulse a single cool-blue colour in lockstep (4 s period) |
| rainbow_sync   | both shift through the HSV wheel together (20 s rotation)   |
| dawn           | both fade red → orange → yellow → soft white over 60 s       |

## Run them

```
venator unified anim list
venator unified anim rainbow_sync
venator unified anim color_pulse --timeout 60
```

Ctrl-C stops the animation and leaves both lights at their last frame.
Use `--timeout N` to auto-stop after N seconds.

## Custom animations

Drop your own `.py` file in
`~/.config/venator/animations/unified/`. The runner picks it
up automatically — no rebuild needed.

A 6 FPS limit is recommended: the WMBH WMI path takes ~10 ms per
write, so going much faster than 10 FPS will saturate the EC and
the animation will stutter. The shipped animations all run at 6 FPS
or below.
