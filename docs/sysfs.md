# sysfs ABI — `/sys/class/venator/keyboard<N>/`

Stable surface for `cli/venator` and any GUI. One device directory per matched keyboard MCU (currently always exactly one on PH16-71).

## Control attributes

All control writes are **staged** — they update the driver's pending state but do not touch the hardware. Commit with `apply`. This lets a GUI move several sliders without flooding the USB bus with intermediate states.

| Attr | Mode | Type | Meaning |
|------|------|------|---------|
| `mode`       | rw | string  | See "Available modes" below. Default `static`. |
| `color`      | rw | string  | Primary colour as `#RRGGBB` (or `RRGGBB`). Honoured by every mode that paints a single colour (everything except `off`, `rainbow`, `neon`, and `perkey`). Default `#ffffff`. |
| `brightness` | rw | u8      | `0..255`. Default `200`. `0` is fully off regardless of `mode`. |
| `effect_id`  | rw | u8      | `0..255`. **Escape hatch.** Write `0` (default) to use the mode's built-in EFF byte; write any other value to send it as the raw EFF byte in the next APPLY. Useful for reaching effect variants we haven't named (the keyboard has many EFF aliases that differ in speed / direction). |
| `frame`      | rw | binary, 384 B | Per-key RGB buffer, 128 cells × 3 bytes `(R, G, B)`. Only sent to hardware when `mode == perkey`. Pre-allocated, can be partially written at any offset. |
| `apply`      | wo | int     | Write `1` to push the current `mode` + `color` + `brightness` + (if `perkey`) `frame` to the hardware in a single transaction. Writing `0` is a no-op. |

### Available modes

Verified by EFF fuzzing on a PH16-71. Several other EFF bytes the
hardware accepts are aliases (often differing only in speed or
direction); they're reachable via `effect_id`.

| `mode`      | EFF  | Uses `color`? | Description |
|-------------|-----:|:-------------:|-------------|
| `off`       |  —   | n/a           | LEDs off (sends EFF=`static` with brightness 0). |
| `static`    | 0x01 | yes           | Solid colour, every key the same. |
| `breathing` | 0x02 | yes           | Solid colour fading in and out. |
| `rainbow`   | 0x03 | no            | Multi-colour wave flowing across the deck. Palette is fixed. |
| `snake`     | 0x05 | yes           | Single-colour wave of ~5 lit keys traveling row by row. |
| `ripple`    | 0x06 | yes           | Reactive: concentric ripple radiates from each keypress. |
| `neon`      | 0x08 | no            | All keys the same hue, slowly cycling through the spectrum. |
| `rain`      | 0x0a | yes           | Random keys flicker like rain drops; slow. |
| `explosion` | 0x12 | yes           | Auto-firing radial bursts at random keys. |
| `pulse`     | 0x25 | yes           | All keys at low brightness; each keypress pulses bright on that key. |
| `stars`     | 0x26 | yes           | Random keys twinkle in and out, slow. |
| `meteor`    | 0x27 | yes           | Reactive directional fireball on each keypress. |
| `aura`      | 0x28 | yes           | Reactive area around the pressed key, sticky while held. |
| `perkey`    | 0x33 | per-cell      | Software paints each of the 128 cells. Write the 384-byte RGB buffer to `frame`, then set `mode=perkey` and `apply`. |

### Reaching unnamed effect variants

The board has more EFF bytes than named modes (e.g. `0x07` ≈ `0x06`,
`0x14` ≈ `0x12`, etc. — same effect family with different speed or
direction). Use `effect_id`:

```bash
cd /sys/class/venator/keyboard0
echo '#ff0000' > color
echo 200       > brightness
echo static    > mode      # keeps MODE_TAG and SCOPE consistent
echo 0x14      > effect_id # override -- send EFF=0x14 instead of 0x01
echo 1         > apply
# When you're done:
echo 0 > effect_id         # back to mode-default
```

## Info subgroup (read-only)

```
info/
├── dev_vendor         "04f2"
├── dev_product        "0117"
├── dev_name           "AcerUSBKeyboard PH16-71"
├── num_cells          "128"
└── available_modes    "off static breathing rainbow snake ripple neon rain explosion pulse stars meteor aura perkey"
```

## Examples

Solid red, full brightness:

```bash
cd /sys/class/venator/keyboard0
echo static  > mode
echo "#ff0000" > color
echo 255     > brightness
echo 1       > apply
```

Off:

```bash
echo off > mode
echo 1   > apply
```

All keys green via per-key path:

```bash
python3 -c "import sys; sys.stdout.buffer.write(bytes([0x00, 0xff, 0x00] * 128))" \
    | sudo tee /sys/class/venator/keyboard0/frame >/dev/null
echo perkey > mode
echo 1      > apply
```
