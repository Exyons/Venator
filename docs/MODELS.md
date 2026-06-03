# Model support matrix

The driver is gated by DMI matching; only models in the "tested" column
will be probed. Everything else falls through to `acer_wmi`.

## Status legend

- ✅ working — feature confirmed by the maintainer or a reproducible report
- 🟡 partial — loads, hardware responds, but not all sub-features
- ❌ broken — known not to work, do not enable
- ⬜ untested — no data either way; do not enable

## Matrix

| `system-product-name` | BIOS range | RGB | Turbo | Fans | Battery | Notes |
|-----------------------|------------|-----|-------|------|---------|-------|
| Predator PH16-71      | INSYDE V1.16 (2023-11-02) | ⬜ HID-PERKEY path planned | ⬜ | ⬜ | ⬜ | **primary target** — `04F2:0117` USB HID, codename `Helios_16_Discovery_RTX` |
| Predator PHN16-71     |            | (Linuwu-Sense) | ⬜ | ⬜ | ⬜ | Helios Neo — different chassis, EC/WMI 4-zone keyboard |
| Predator PHN16-72     |            | ⬜  | ⬜    | ⬜   | ⬜      |       |
| _add as reports come in_ |         |     |       |      |         |       |

## Adding a model

1. Collect the machine's identity: `cat /sys/class/dmi/id/product_name`
   and the keyboard's USB id from `lsusb` (the PH16-71 is `04F2:0117`).
2. Open an issue with that info, plus the contents of `/sys/class/predator/`
   once the module is loaded (or a note that the keyboard stays dark).
3. If the USB-HID id and WMI GUIDs match the PH16-71, add a DMI match row
   in `kernel/venator-main.c` and a row to this table.
4. If they differ, treat it as a new target and coordinate in the issue
   before enabling — the wire protocol may not be identical.
