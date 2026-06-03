# Unified themes

Each `.json` here is a single "scene" that drives both the keyboard
and the rear lightbar to a coordinated state in one command. Shipped
themes:

| name        | what it does                                                    |
|-------------|-----------------------------------------------------------------|
| red-alert   | both static red, bright                                         |
| ocean       | both breathing blue                                             |
| forest      | keyboard static green, lightbar breathing green                 |
| sunset      | both breathing warm orange                                      |
| rainbow     | both running the firmware's rainbow mode                        |
| cyber-mauve | keyboard breathing magenta, lightbar neon magenta               |
| off         | everything off                                                  |

Use:

```
venator unified list                   # show themes
venator unified apply ocean            # apply a built-in
venator unified apply ~/my-theme.json  # apply from disk
```

## Schema

```json
{
  "name":        "string, required",
  "description": "string, optional",
  "keyboard": {
    "mode":       "off|static|breathing|rainbow|snake|ripple|neon|rain|...",
    "color":      "#RRGGBB",
    "brightness": 0..255,
    "speed":      0..255   // optional, ignored by static modes
  },
  "lightbar": {
    "mode":       "off|breathing|neon|rainbow|wave|ripple|scanner|strobe|static",
    "color":      "#RRGGBB",
    "brightness": 0..255,
    "speed":      0..255
  }
}
```

The `keyboard` and `lightbar` sections are independent — you can use a
breathing keyboard with a static lightbar, etc. Either section may be
omitted to leave that side alone.

User themes live at `~/.config/venator/designs/unified/`. They
override the shipped ones if the names collide.
