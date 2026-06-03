# Install

End-to-end setup for the Predator Helios 16 (PH16-71). Tested on
Fedora 43 + CachyOS 7.0.5 with Secure Boot **enabled**. Other distros
should work; the only Fedora-specific detail is the MOK signing
recipe.

## 1. Kernel module

Three methods, all run via `packaging/fedora/install.sh`. Each ends with
the module loaded, `/etc/modules-load.d/venator.conf` in place
(auto-load at boot), and the MOK signing handled. **You pick which.**

- **`hook` (recommended on Fedora)** — installs a `kernel-install` hook
  that rebuilds + re-signs the module on every kernel upgrade. No
  akmods, no SRPM, no daemon.
- **`akmods` (Fedora alternative)** — same auto-rebuild via
  `akmods.service`. Heavier; kept as a fallback.
- **`manual` (any distro)** — one-shot build for the current kernel;
  re-run after each kernel upgrade.

### 1a-hook. kernel-install hook (recommended, Fedora)

```bash
sudo dnf install kernel-devel-$(uname -r) make gcc
sudo make hook-install                                   # = install.sh --hook
```

What it does:

1. Autodetects/creates an akmods-style signing key under `/etc/pki/akmods/`.
2. Stages the sources to `/usr/src/venator/`.
3. Installs the hook to `/etc/kernel/install.d/99-venator.install`.
4. Builds + signs + installs once for the running kernel, then modprobes.

On every future `kernel-install add KVER` (run by the kernel RPM
scriptlets on upgrade) the hook rebuilds, signs, installs to
`/lib/modules/$KVER/extra/venator/`, and depmods. It always
exits 0 so it can never block a kernel install; errors land in
`journalctl -t venator-hook -b`.

### 1a. Manual (works on any distro / any kernel)

```bash
sudo dnf install kernel-devel-$(uname -r) make gcc       # or distro equivalent
sudo make manual-install                                 # = ./packaging/fedora/install.sh
```

What it does:

1. **Autodetect signing keys**, in this order:
   - any `*.priv` in `/etc/pki/akmods/private/` + any `*.der|*.cer|*.crt`
     in `/etc/pki/akmods/certs/` (covers the case where akmods has
     already generated keys for another module like akmod-nvidia — we
     reuse them, no symlinks);
   - `/var/lib/shim-signed/mok/MOK.{priv,der}`.
   You can override with `--mok-priv PATH --mok-cert PATH`, or skip
   signing entirely with `--no-sign` (only safe if SecureBoot is off).
2. Builds against `/lib/modules/$(uname -r)/build`.
3. Signs the `.ko` with the detected key.
4. Installs to `/lib/modules/$(uname -r)/extra/venator/`.
5. `depmod -a`, writes modules-load.d, modprobes.

Trade-off: you re-run this after every kernel upgrade.

### 1b. Akmods (Fedora; auto-rebuilds across kernel upgrades)

```bash
sudo dnf install akmods kmodtool rpm-build
sudo make akmods-install
```

What it does:

1. Reuses existing akmods keys if any are in `/etc/pki/akmods/`.
   Otherwise generates a fresh akmods key and prints the
   `mokutil --import` line for you to enrol.
2. Builds **both** the `akmod-venator.noarch.rpm` metapackage
   and the SRPM from `packaging/fedora/venator-kmod.spec`
   (kmodtool-driven).
3. `dnf install`s the akmod-* metapackage. Its `%post` triggers
   `akmods`, which rebuilds the kmod for the current kernel.
4. `dnf install`s the resulting `kmod-venator-<ver>-<kver>.x86_64.rpm`.
5. modules-load.d + modprobe.

After this, `akmods.service` (enabled by default) handles per-kernel
rebuilds on every upgrade — including the signing, because it reuses
the same key.

**Caveat:** akmods + kmodtool sometimes choke on non-stock kernels
(CachyOS, Liquorix, etc.) because the kernel-devel package naming is
non-standard. If `--akmods` fails for you, fall back to `--manual`.

### install.sh flags reference

```
--hook                kernel-install hook; auto-rebuild on every upgrade (recommended)
--manual              (default) build + sign + install for current kernel
--akmods              hand build to akmods; auto-rebuild on upgrade
--mok-priv PATH       explicit MOK private key
--mok-cert PATH       explicit MOK cert (.der / .cer / .crt)
--no-sign             don't sign (SecureBoot off only)
-h, --help            help
```

Full play-by-play of the akmods spec + the kmodtool plumbing lives in
`packaging/fedora/README.md`.

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
sudo groupadd -r predator
sudo usermod -aG predator $USER
sudo udevadm control --reload
sudo udevadm trigger -s predator
newgrp predator           # or log out and log back in
```

Verify:

```bash
ls -l /sys/class/predator/keyboard0/mode
# expect: -rw-rw-r-- 1 root predator ...
venator status     # no sudo!
venator rgb static '#ff0000'
```

If the group/mode columns still show `root root` and `-rw-r--r--`, the
udev rule didn't fire. Verify:

```bash
udevadm test /sys/class/predator/keyboard0 2>&1 | grep predator
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
sudo make uninstall            # everything: kernel module (hook/akmods/manual),
                               # userspace, units, modules-load.d. Also removes the
                               # kernel-install hook + /usr/src/venator.
```

Per-user state (`~/.config/venator/{profiles,keymap.json,animations,designs}`)
is left alone. Remove it manually if you want a clean wipe.
