# Fedora kernel-install hook

This directory holds **`99-venator.install`** — the Fedora `kernel-install`
hook that the OS-aware installer (`install.sh`, at the **repo root**) deploys
when it runs in `--hook` mode. The installer itself is no longer here; it's a
global, distro-agnostic script at the top of the tree.

`install.sh` is **OS-aware**. The default (`--auto`) reads `/etc/os-release`
and runs the routine that fits the distro:

- **Fedora / RHEL-like → `--hook`** — installs `99-venator.install` into
  `/etc/kernel/install.d/` so every kernel upgrade re-builds + re-signs the
  module with zero external moving parts (no akmods, no SRPM, no daemon).
- **Arch / CachyOS / other → `--manual`** — distro-agnostic one-shot:
  build, sign, install, load. Re-run after every kernel upgrade.

## Quick install

```bash
# Run from the repo root. Auto-detect the OS and pick hook (Fedora) or
# manual (Arch/CachyOS).
sudo ./install.sh

# Force a routine:
sudo ./install.sh --hook       # Fedora kernel-install hook
sudo ./install.sh --manual     # one-shot build for current kernel

sudo ./install.sh --secureboot # auto-detect OS + sign for Secure Boot
sudo ./install.sh --uninstall  # remove the module + everything it installed
```

The module is **unsigned by default** (non-Secure Boot). Add `--secureboot`
to sign. All paths set up `/etc/modules-load.d/venator.conf`, so the module
loads on boot from now on. From the repo root the same routines are
`sudo make module-install` / `hook-install` / `manual-install`, with
`SECUREBOOT=1` to sign.

## install.sh flags

```
--auto                (default) detect OS: Fedora -> hook, Arch/other -> manual
--hook                kernel-install hook; auto-rebuild on every kernel upgrade (Fedora)
--manual              build / install for current kernel
--secureboot          sign the module (off by default); resolves a key
--mok-priv PATH       explicit signing private key (.priv/.key); implies --secureboot
--mok-cert PATH       explicit signing cert (.der/.cer/.crt/.pem); implies --secureboot
--no-sign             explicitly disable signing (the default)
--uninstall           remove the module + everything install.sh installs
--skip-group          don't create the venator group / set udev perms
-h, --help            show this help
```

## How hook mode works (Fedora)

`install.sh --hook` does:

1. With `--secureboot`: auto-detect or generate akmods-style signing keys at
   `/etc/pki/akmods/` (skipped by default).
2. Copy the kernel sources to `/usr/src/venator/`.
3. Install the hook script to `/etc/kernel/install.d/99-venator.install`.
4. Run the hook once for the current kernel (`add $(uname -r)`).
5. `modprobe venator`.

The hook itself, on every `kernel-install add KVER` (which the kernel
RPM scriptlets run after install) does:

1. `cp -a /usr/src/venator/ <tmpdir>/` (don't pollute the source tree).
2. `make -C /lib/modules/$KVER/build M=<tmpdir> modules`.
3. `sign-file sha256 <key> <cert> venator.ko` using the first
   `*.priv` + `*.der|.cer|.crt` it finds under `/etc/pki/akmods/`.
4. `install -Dm644 venator.ko /lib/modules/$KVER/extra/venator/`.
5. `depmod -a $KVER`.

It always `exit 0` regardless of build success — kernel-install must
not be blocked by an out-of-tree module. If the build fails (typically
because `kernel-devel` isn't installed for that kernel), the error
lands in journald: `journalctl -t venator-hook -b`.

The `remove` arm of the hook deletes `/lib/modules/$KVER/extra/venator/`
when kernel-install removes a kernel, keeping `/lib/modules/` clean.

## How manual mode works (Arch / CachyOS / any)

`install.sh --manual` does:

1. `make -C kernel`. The module Makefile auto-detects a **Clang/LLD-built**
   kernel (`CONFIG_CC_IS_CLANG=y`) and adds `LLVM=1` — required on CachyOS,
   where building with GCC against a Clang kernel fails on `-mllvm`,
   `-mretpoline-external-thunk`, `-mstack-alignment=8`, etc.
2. With `--secureboot`: sign the `.ko` with `sign-file` and the auto-detected
   key (see below). `sign-file` is located under either
   `/lib/modules/$KVER/build/scripts/` (Arch/CachyOS) or
   `/usr/src/kernels/$KVER/scripts/` (Fedora). Skipped by default.
3. Install to `/lib/modules/$KVER/extra/venator/`, `depmod -a`, write
   modules-load.d, `modprobe`.

A pacman hook for automatic rebuilds on kernel upgrade is planned; for now,
re-run after each upgrade.

### Signing (opt-in via `--secureboot`)

Signing is **off by default** — the module installs unsigned, which loads on
non-Secure-Boot systems (and on CachyOS even with Secure Boot, since its
kernel doesn't enforce module signatures; `lockdown` is `none`).

With `--secureboot` (or explicit `--mok-priv`/`--mok-cert`) the script
resolves a key in this order:

1. **akmods-managed**: any `*.priv` under `/etc/pki/akmods/private/` and
   any `*.der|*.cer|*.crt` under `/etc/pki/akmods/certs/` (reuses a key
   akmods already generated, e.g. for akmod-nvidia).
2. **shim-signed MOK**: `/var/lib/shim-signed/mok/MOK.{priv,der}`.
3. **sbctl** (Arch / CachyOS): `/var/lib/sbctl/keys/db/db.{key,pem}`. The
   module is signed with this `db` keypair via `sign-file`. Note that
   `sbctl sign` itself only signs **EFI binaries** (PE format) — it rejects
   ELF kernel modules — so we use its key with `sign-file` instead.

If `--secureboot` is set but no key is found, the script errors out: pass
`--mok-priv` / `--mok-cert`, set up sbctl (`sbctl create-keys`), or on Fedora
use `--hook --secureboot` (which generates an akmods key). Without
`--secureboot`, a missing key is fine — the module is just left unsigned. If
Secure Boot is enforcing and you didn't sign, the installer warns you.

## Uninstall

```bash
# Any install method (top-level Makefile handles both paths):
sudo make uninstall

# By hand, hook install:
sudo rmmod venator
sudo rm -f /etc/kernel/install.d/99-venator.install
sudo rm -rf /usr/src/venator
sudo rm -rf /lib/modules/*/extra/venator
sudo rm -f  /etc/modules-load.d/venator.conf
sudo depmod -a

# By hand, manual install:
sudo rmmod venator             # if loaded
sudo rm -f /lib/modules/*/extra/venator/venator.ko
sudo rm -f /etc/modules-load.d/venator.conf
sudo depmod -a
```

`/etc/pki/akmods/` and `/var/lib/sbctl/` are left alone in either case —
other packages share those keys.

## Troubleshooting

- **`unrecognized command-line option '-mllvm'` (and friends) on CachyOS**:
  the kernel is Clang-built and the module was built with GCC. The Makefile
  now auto-detects this and passes `LLVM=1`; if you build by hand, run
  `make -C kernel LLVM=1`. Needs `clang lld llvm` installed.
- **Module loads but SecureBoot rejects it** (Fedora): the cert under
  `/etc/pki/akmods/certs/` isn't enrolled. Run
  `sudo mokutil --import /etc/pki/akmods/certs/<your-cert>.der`, reboot,
  enrol in MOK Manager.
- **`Key was rejected by service`**: the signing key isn't trusted by the
  kernel's module keyring. On Arch/CachyOS with SecureBoot enforcement off
  this doesn't happen (unsigned/any-signed modules load); if you see it,
  module-signature enforcement is on and the key needs enrolling (MOK / db).
- **Hook ran but no module installed** (Fedora): check `journalctl -t
  venator-hook -b`. Most common cause is `kernel-devel` not installed for
  the new kernel. After `dnf install kernel-devel-$(uname -r)`, re-trigger
  with `sudo /etc/kernel/install.d/99-venator.install add $(uname -r)`.
