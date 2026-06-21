# Install

End-to-end setup for the Predator Helios 16 (PH16-71). Tested on
Fedora 43 + CachyOS 7.0.5 with Secure Boot **enabled**. The kernel-module
step is **OS-aware**: it detects Fedora vs Arch/CachyOS and runs the right
build + signing routine.

## 1. Kernel module

One command does the right thing per distro:

```bash
sudo make module-install        # = ./install.sh --auto
```

`install.sh` reads `/etc/os-release` (`ID` / `ID_LIKE`) and dispatches:

- **Fedora / RHEL-like → `hook`** — installs a `kernel-install` hook that
  rebuilds + re-signs the module on every kernel upgrade.
- **Arch / CachyOS / other → `manual`** — one-shot build for the current
  kernel; re-run after each kernel upgrade.

Force a routine with `sudo make hook-install` or `sudo make manual-install`.
Either way the module ends up loaded and `/etc/modules-load.d/venator.conf`
is in place (auto-load at boot).

**Signing is OFF by default** (non-Secure Boot). To sign for Secure Boot,
add `SECUREBOOT=1` to any target (e.g. `sudo make module-install
SECUREBOOT=1`) — see [1c. Secure Boot](#1c-secure-boot-signing).

### 1a. Fedora — kernel-install hook

```bash
sudo dnf install kernel-devel-$(uname -r) make gcc
sudo make hook-install                                   # = install.sh --hook
# signed:  sudo make hook-install SECUREBOOT=1
```

What it does:

1. Stages the sources to `/usr/src/venator/`.
2. Installs the hook to `/etc/kernel/install.d/99-venator.install`.
3. Builds + installs once for the running kernel, then modprobes.
   With `SECUREBOOT=1` it first autodetects/creates an akmods-style signing
   key under `/etc/pki/akmods/` and signs.

On every future `kernel-install add KVER` (run by the kernel RPM
scriptlets on upgrade) the hook rebuilds, (re-signs if a key exists),
installs to `/lib/modules/$KVER/extra/venator/`, and depmods. It always
exits 0 so it can never block a kernel install; errors land in
`journalctl -t venator-hook -b`.

### 1b. Arch / CachyOS — manual build

```bash
sudo pacman -S --needed base-devel linux-cachyos-headers   # or linux-headers
sudo make manual-install                                   # = install.sh --manual
# signed:  sudo make manual-install SECUREBOOT=1
```

What it does:

1. Builds against `/lib/modules/$(uname -r)/build`. CachyOS kernels are
   **Clang/LLD-built**; the module Makefile detects `CONFIG_CC_IS_CLANG=y`
   and adds `LLVM=1` automatically (building with GCC against a Clang
   kernel fails on `-mllvm`, `-mretpoline-external-thunk`, etc.).
2. Installs to `/lib/modules/$(uname -r)/extra/venator/`, `depmod -a`,
   writes modules-load.d, modprobes. Unsigned unless `SECUREBOOT=1`.

CachyOS doesn't enforce module signatures (`lockdown` is `none`), so the
unsigned module loads even with Secure Boot enabled. Trade-off: re-run after
every kernel upgrade.

### 1b′. Debian / Ubuntu (and any other distro) — manual build

The `--manual` routine is the **universal one-shot** path; it works on any
distro with kernel headers + a C toolchain + systemd, not just Arch.

```bash
# Debian / Ubuntu / Mint / Pop!_OS:
sudo apt install linux-headers-$(uname -r) build-essential
sudo ./install.sh                  # auto-detects -> manual on non-Fedora
```

It builds against `/lib/modules/$(uname -r)/build`, installs to
`/lib/modules/$(uname -r)/extra/venator/`, `depmod`s, writes modules-load.d,
and modprobes — identical to the Arch path. If `install.sh` can't find the
kernel headers it aborts with a per-distro install hint.

**Auto-rebuild on kernel upgrade is currently Fedora-only** (the
kernel-install hook). On Arch, Debian/Ubuntu, and every other distro, re-run
`sudo ./install.sh` after a kernel upgrade. A cross-distro DKMS path is planned.

### 1c. Secure Boot (signing)

Signing is opt-in. Add `SECUREBOOT=1` (or pass `--secureboot` to
`install.sh`). The installer resolves a key in this order:

1. akmods keys under `/etc/pki/akmods/` (priv + der/cer/crt);
2. `/var/lib/shim-signed/mok/MOK.{priv,der}`;
3. **sbctl** `db` keypair at `/var/lib/sbctl/keys/db/db.{key,pem}`.

It signs the `.ko` via the kernel's `sign-file`. (`sbctl sign` itself only
handles EFI binaries, not ELF modules — we use its key with `sign-file`.)
Provide your own with `--mok-priv PATH --mok-cert PATH`. On Fedora `--hook`,
if no key exists one is generated and the `mokutil --import` line printed for
you to enroll. If `SECUREBOOT=1` is set but no key is found, the install
aborts rather than producing a module that won't load.

### install.sh flags reference

```
--auto                (default) detect OS: Fedora -> hook, Arch/other -> manual
--hook                kernel-install hook; auto-rebuild on every upgrade (Fedora)
--manual              build + install for current kernel
--secureboot          sign the module (off by default); resolves a key
--mok-priv PATH       explicit signing private key (.priv/.key); implies --secureboot
--mok-cert PATH       explicit signing cert (.der/.cer/.crt/.pem); implies --secureboot
--no-sign             explicitly disable signing (the default)
--uninstall           remove the module + everything install.sh installs
--skip-group          don't create the venator group / set udev perms
-h, --help            help
```

## 2. Userspace

```bash
sudo make install
# or:
sudo make install PREFIX=/usr
```

That installs:

| File                                                | From repo                            |
|-----------------------------------------------------|--------------------------------------|
| `$PREFIX/bin/venator`                        | `cli/venator`                 |
| `$PREFIX/share/venator/animations/*`         | `cli/animations/`                    |
| `$PREFIX/share/venator/designs/*`            | `cli/designs/`                       |
| `$PREFIX/share/venator/keymaps/*`            | `cli/keymaps/`                       |
| `/etc/udev/rules.d/70-venator.rules`         | `udev/70-venator.rules`       |
| `/etc/systemd/user/venator-restore.service`  | `systemd/...`                        |

## 3. Drop the sudo

```bash
sudo groupadd -r venator
sudo usermod -aG venator $USER
sudo udevadm control --reload
sudo udevadm trigger -s venator
newgrp venator           # or log out and log back in
```

Verify:

```bash
ls -l /sys/class/venator/keyboard0/mode
# expect: -rw-rw-r-- 1 root venator ...
venator status     # no sudo!
venator rgb static '#ff0000'
```

If the group/mode columns still show `root root` and `-rw-r--r--`, the
udev rule didn't fire. Verify:

```bash
udevadm test /sys/class/venator/keyboard0 2>&1 | grep venator
```

Most common cause: the module was loaded before `udevadm control --reload`.
`sudo modprobe -r venator && sudo modprobe venator` after the
reload forces the rule to run.

## 4. Restore-at-login + live power switching

`make install` enables two **user** services for the invoking user (so
you usually don't need to do anything):

```bash
# Restore the last keyboard + lightbar scheme AND the power profile for
# the current power source at login. Every `rgb`/`lightbar` command
# auto-saves the "default" profile, so no manual snapshot is needed.
systemctl --user enable --now venator-restore

# Watch the AC adapter and switch the power profile in real time on
# plug/unplug (per the AC/battery power-policy). Without this the
# policy is only applied at login.
systemctl --user enable --now venator-powerwatch
```

The AC/battery policy itself is configured with `venator
power-policy` (see the README's *Power & thermal* section). First-use
defaults: Balanced on AC, Quiet on battery.

To swap which RGB profile gets restored, edit
`/etc/systemd/user/venator-restore.service` or override per-user
via `~/.config/systemd/user/venator-restore.service`.

## Uninstall

```bash
sudo make uninstall            # everything: kernel module (hook or manual),
                               # userspace, units, modules-load.d. Also removes the
                               # kernel-install hook + /usr/src/venator.

# kernel-module side only (module, hook, /usr/src/venator, modules-load.d,
# udev rule, venator group) without touching the userspace CLI:
sudo ./install.sh --uninstall
```

Per-user state (`~/.config/venator/{profiles,keymap.json,animations,designs}`)
is left alone. Remove it manually if you want a clean wipe.
