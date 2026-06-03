# Fedora packaging — kernel module install

Three install paths. **`--hook` is the recommended one on Fedora**: it
hooks into Fedora's own `kernel-install` so every kernel upgrade
re-builds + re-signs the module with zero external moving parts
(no akmods, no SRPM, no daemon). **`--akmods`** is the older, more
elaborate equivalent and kept as a fallback. **`--manual`** is the
distro-agnostic one-shot — works everywhere, but you re-run it after
every kernel upgrade.

## Quick install

```bash
# Recommended on Fedora: stash sources to /usr/src/venator and
# install a hook at /etc/kernel/install.d/. Every `kernel-install add`
# (run by the kernel RPM scriptlet) re-builds + re-signs + depmods.
sudo ./install.sh --hook

# Manual: builds, signs with your MOK, installs to /lib/modules/.../extra,
# modules-load.d, modprobes. Re-run after each kernel upgrade.
sudo ./install.sh

# Akmods: hands the build to akmods so kernel upgrades auto-rebuild.
sudo ./install.sh --akmods
```

All paths set up `/etc/modules-load.d/venator.conf`, so the
module loads on boot from now on.

## install.sh flags

```
--hook                kernel-install hook; auto-rebuild on every kernel upgrade
--manual              (default) build / sign / install for current kernel
--akmods              hand build to akmods, with auto-rebuild on upgrade
--mok-priv PATH       explicit MOK private key (.priv)
--mok-cert PATH       explicit MOK cert (.der / .cer / .crt)
--no-sign             skip signing (only safe if SecureBoot is off)
-h, --help            show this help
```

## How hook mode works

`install.sh --hook` does:

1. Auto-detect or generate akmods-style signing keys at `/etc/pki/akmods/`.
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

### Key autodetect

Without `--mok-priv` / `--mok-cert`, the script looks for keys in this
order:

1. **akmods-managed**: any `*.priv` under `/etc/pki/akmods/private/` and
   any `*.der|*.cer|*.crt` under `/etc/pki/akmods/certs/`. This covers
   the case where akmods already generated a key for you (e.g. while
   installing the nvidia driver), so we just reuse it — no symlink
   surgery.
2. **shim-signed MOK**: `/var/lib/shim-signed/mok/MOK.{priv,der}`.

If neither is present and you're using `--akmods`, the script asks
`akmods-keygen` to generate one and prints the `mokutil --import` line.

If neither is present in `--manual` mode, the script errors out — pass
`--mok-priv` / `--mok-cert` explicitly, or `--no-sign`.

## How akmods mode actually works

The spec at `venator-kmod.spec` uses **kmodtool** macros to
generate the standard rpmfusion-style subpackages:

| Output                                    | Description |
|-------------------------------------------|-------------|
| `akmod-venator-<ver>.noarch.rpm`   | Metapackage. Ships the SRPM at `/usr/src/akmods/`. Has a `%post` that triggers `akmods` to rebuild the kernel-specific kmod. |
| `venator-kmod-<ver>-*.src.rpm`     | Source RPM. akmods rebuilds this with `--define "kernels <kver>"` for each installed kernel. |
| `kmod-venator-<ver>-<kver>.x86_64.rpm` | Per-kernel built module + signed `.ko`. Lands in `/var/cache/akmods/` for dnf install. |

`install.sh --akmods` does the full chain:

1. Auto-detect / generate akmods signing keys at `/etc/pki/akmods/`.
2. Tarball the kernel sources.
3. `rpmbuild -ba` to produce the akmod-* noarch RPM and the SRPM.
4. `dnf install akmod-venator-*.noarch.rpm` — its `%post`
   triggers akmods.
5. `akmods --kernels $(uname -r) --force` (belt-and-braces, in case
   `%post` raced with the script).
6. Find the built `kmod-venator-<ver>-<kver>.x86_64.rpm` under
   `/var/cache/akmods/` and `dnf install` it.
7. Drop `/etc/modules-load.d/venator.conf` + `modprobe`.

After this, kernel upgrades trigger `akmods.service` (enabled by
default), which rebuilds + re-signs against the new kernel before
anything tries to load the module.

## Why we ship three methods

- `--hook` is the simplest path on Fedora. No external service, no
  SRPM, no akmod-* metapackage, no extra dependencies beyond
  `kernel-devel` and a signing key. Survives kernel upgrades by
  piggybacking on the same `kernel-install` invocation the kernel RPM
  already does. Recommended for almost everyone.
- `--manual` works **everywhere**, no RPM / akmods / kernel-install
  dependency. Great for Arch, custom-kernel users, debugging, etc.
  Downside: re-run after each kernel upgrade.
- `--akmods` is the original Fedora-native option and survives kernel
  upgrades via `akmods.service`. Depends on `akmods`, `kmodtool`, and
  `rpm-build`. If anything in that chain fails on a non-stock kernel
  (we saw issues on `cachyos1.fc43`), `--hook` or `--manual` are
  reliable fallbacks.

## Uninstall

```bash
# Any install method (top-level Makefile handles all three paths):
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

`/etc/pki/akmods/` is left alone in either case — other akmods packages
(e.g. akmod-nvidia) may share those keys.

## Troubleshooting

- **`Checking kmods exist [OK]` then nothing built**: this is what
  happens when akmods can't find an installed `akmod-*` metapackage
  for our module. The old hand-rolled spec produced an SRPM named
  `venator-kmod-*.src.rpm` but no metapackage; akmods's
  precheck just says "nothing to do". The current spec uses kmodtool
  so it produces both the metapackage and the SRPM properly.
- **`/var/cache/akmods/<...>.failed.log`**: per-kernel build log, useful
  if `rpmbuild --rebuild` fails inside akmods. Common causes:
  matching `kernel-devel` not installed; non-stock kernel naming.
- **Module loads but SecureBoot rejects it**: the cert under
  `/etc/pki/akmods/certs/` isn't enrolled. Run
  `sudo mokutil --import /etc/pki/akmods/certs/<your-cert>.der`,
  reboot, enrol in MOK Manager.
- **Akmods fails on CachyOS**: the kernel-devel naming is non-stock.
  Fall back to `--hook` or `--manual` — neither cares about RPM metadata.
- **Hook ran but no module installed**: check `journalctl -t
  venator-hook -b`. Most common cause is `kernel-devel` not
  installed for the new kernel. Once you `dnf install kernel-devel-$(uname
  -r)`, re-trigger by running
  `sudo /etc/kernel/install.d/99-venator.install add $(uname -r)`.
