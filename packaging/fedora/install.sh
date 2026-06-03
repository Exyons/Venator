#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
#
# venator kernel-module installer.
#
# By default this builds the module against the running kernel, signs
# with your existing MOK (auto-detected), installs to
# /lib/modules/$(uname -r)/extra/, depmods, and modprobes it. Works on
# any distro (no RPM required).
#
# Pass --akmods to instead hand the build off to Fedora's akmods. If
# kmodtool can produce the akmod-* metapackage you get full per-kernel
# auto-rebuild. If kmodtool only produces the kmod-* RPM (some kmodtool
# versions on non-stock kernels do this), we install that directly and
# stash the SRPM under /usr/src/akmods/ so akmods.service can rebuild
# from it on the next boot after a kernel upgrade.

set -euo pipefail

# ---------------- colour helpers --------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_GREEN=$'\033[0;32m'
    C_YELLOW=$'\033[1;33m'
    C_RED=$'\033[0;31m'
    C_BOLD=$'\033[1m'
    C_DIM=$'\033[2m'
    C_RESET=$'\033[0m'
else
    C_GREEN=''; C_YELLOW=''; C_RED=''; C_BOLD=''; C_DIM=''; C_RESET=''
fi

step() { printf '%s==>%s %s\n'   "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s!! %s%s\n'    "$C_YELLOW" "$*" "$C_RESET" >&2; }
fail() { printf '%sxx %s%s\n'    "$C_RED"   "$*" "$C_RESET" >&2; exit 1; }
info() { printf '   %s%s%s\n'    "$C_DIM"   "$*" "$C_RESET"; }

usage() {
    cat <<'EOF'
venator kernel module installer

Usage: install.sh [METHOD] [SIGNING] [-h]

Methods:
  --hook     (recommended on Fedora) Stash sources at /usr/src/venator
                        and drop a kernel-install hook at
                        /etc/kernel/install.d/99-venator.install.
                        Every `kernel-install add` (run automatically by
                        the kernel RPM scriptlets on every upgrade)
                        re-builds + re-signs the module. No akmods,
                        no SRPM, no daemon. Then builds once now.
  --manual   (default)  Build for the current kernel, sign, install to
                        /lib/modules/$(uname -r)/extra/, modules-load.d
                        + modprobe. Works on any distro / any kernel.
                        Re-run after each kernel upgrade.
  --akmods              Build + install via akmods. Requires `akmods`
                        and `rpm-build`. Tries the akmod-* metapackage
                        flow first; falls back to direct kmod install
                        if kmodtool didn't produce the metapackage.

Signing (auto-detected if omitted, in this order):
  1. /etc/pki/akmods/private/*.priv  +  /etc/pki/akmods/certs/*.{der,cer,crt}
  2. /var/lib/shim-signed/mok/MOK.priv + MOK.der

Signing overrides:
  --mok-priv PATH       Path to a MOK / signing private key (.priv)
  --mok-cert PATH       Path to a MOK / signing certificate (.der/.cer/.crt)
  --no-sign             Don't sign (only safe if SecureBoot is off)

Other:
  --skip-group          Don't create the predator group / set udev perms
  -h, --help            Show this help and exit.

Examples:
  sudo ./install.sh --hook                     # recommended on Fedora
  sudo ./install.sh                            # manual + auto-signed
  sudo ./install.sh --akmods                   # akmods + auto-signed
  sudo ./install.sh --mok-priv ~/MOK.priv \
                    --mok-cert ~/MOK.der       # manual + explicit keys
  sudo ./install.sh --no-sign                  # SecureBoot off
EOF
}

METHOD=manual
MOK_PRIV=""
MOK_CERT=""
DO_SIGN=auto
DO_GROUP=1

while [ $# -gt 0 ]; do
    case "$1" in
        --akmods)     METHOD=akmods ;;
        --manual)     METHOD=manual ;;
        --hook)       METHOD=hook ;;
        --mok-priv)   MOK_PRIV="$2"; shift ;;
        --mok-cert)   MOK_CERT="$2"; shift ;;
        --no-sign)    DO_SIGN=no ;;
        --skip-group) DO_GROUP=0 ;;
        -h|--help)    usage; exit 0 ;;
        *) fail "Unknown arg: $1" ;;
    esac
    shift
done

[ "$(id -u)" -eq 0 ] || fail "Run as root (sudo $0 ...)"

VERSION=0.1.0
PKG_NAME=venator
KVER=$(uname -r)

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
KERNEL_SRC="$REPO_ROOT/kernel"

[ -f "$KERNEL_SRC/venator-main.c" ] || \
    fail "Can't find kernel sources at $KERNEL_SRC/. Run install.sh from a clone of the repo."
[ -d "/lib/modules/${KVER}/build" ] || \
    fail "Missing kernel headers/devel for the running kernel (${KVER}). Install the matching kernel-devel package and re-run."

INVOKER=${SUDO_USER:-}     # the actual user who ran sudo, if any

# ---------- signing key resolution -------------------------------------------

resolve_signing_keys() {
    if [ -n "$MOK_PRIV" ] && [ -n "$MOK_CERT" ]; then
        [ -f "$MOK_PRIV" ] && [ -f "$MOK_CERT" ] || \
            fail "MOK files not found: $MOK_PRIV / $MOK_CERT"
        return
    fi
    # 1. akmods-managed keys: any .priv + any .der|.cer|.crt under /etc/pki/akmods/
    if [ -d /etc/pki/akmods/private ] && [ -d /etc/pki/akmods/certs ]; then
        local p c
        p=$(find /etc/pki/akmods/private -maxdepth 1 -type f -name '*.priv' | head -1)
        c=$(find /etc/pki/akmods/certs   -maxdepth 1 -type f \
                \( -name '*.der' -o -name '*.cer' -o -name '*.crt' \) | head -1)
        if [ -n "$p" ] && [ -n "$c" ]; then
            MOK_PRIV="$p"; MOK_CERT="$c"
            return
        fi
    fi
    # 2. Standard shim-signed MOK
    if [ -f /var/lib/shim-signed/mok/MOK.priv ] && [ -f /var/lib/shim-signed/mok/MOK.der ]; then
        MOK_PRIV=/var/lib/shim-signed/mok/MOK.priv
        MOK_CERT=/var/lib/shim-signed/mok/MOK.der
        return
    fi
    return 1
}

ensure_akmods_keys() {
    local p c
    mkdir -p /etc/pki/akmods/private /etc/pki/akmods/certs
    p=$(find /etc/pki/akmods/private -maxdepth 1 -type f -name '*.priv' 2>/dev/null | head -1)
    c=$(find /etc/pki/akmods/certs   -maxdepth 1 -type f \
            \( -name '*.der' -o -name '*.cer' -o -name '*.crt' \) 2>/dev/null | head -1)
    if [ -n "$p" ] && [ -n "$c" ]; then
        step "akmods signing keys already present at /etc/pki/akmods/"
        info "$p"
        info "$c"
        return
    fi
    step "No akmods key found. Generating..."
    /usr/sbin/akmods-keygen >/dev/null 2>&1 || \
        akmods --genkey      >/dev/null 2>&1 || true
    c=$(find /etc/pki/akmods/certs -maxdepth 1 -type f \
            \( -name '*.der' -o -name '*.cer' -o -name '*.crt' \) 2>/dev/null | head -1)
    [ -n "$c" ] || fail "akmods-keygen failed. Try: sudo /usr/sbin/akmods-keygen"
    warn "SecureBoot: enrol the new key with MOK Manager:"
    warn "    sudo mokutil --import \"$c\""
    warn "Reboot, MOK Manager appears, pick 'Enroll MOK', enter the password you set."
}

# ---------- predator group + udev -------------------------------------------

setup_group_and_udev() {
    [ "$DO_GROUP" -eq 1 ] || return 0

    if ! getent group predator >/dev/null 2>&1; then
        step "Creating 'predator' group"
        groupadd -r predator
    fi

    if [ -n "$INVOKER" ] && [ "$INVOKER" != "root" ]; then
        local added=0
        if ! id -nG "$INVOKER" 2>/dev/null | tr ' ' '\n' | grep -qx predator; then
            step "Adding $INVOKER to 'predator' group"
            usermod -aG predator "$INVOKER"; added=1
        else
            step "$INVOKER already in 'predator' group"
        fi
        # The background worker reads /dev/input/by-path/*-event-kbd to
        # implement wake-on-keypress for our custom designs / animations.
        # On Fedora those devices are root:input 660, so the user needs
        # 'input' group membership for non-sudo invocations to work.
        if ! id -nG "$INVOKER" 2>/dev/null | tr ' ' '\n' | grep -qx input; then
            step "Adding $INVOKER to 'input' group (for keypress detection via /dev/input/event*)"
            usermod -aG input "$INVOKER"; added=1
        fi
        if [ "$added" -eq 1 ]; then
            warn "$INVOKER needs to log out + back in (or 'newgrp predator && newgrp input') for the new groups to take effect."
        fi
    else
        warn "No SUDO_USER set. Add yourself manually:"
        warn "  sudo usermod -aG predator,input <yourname>"
    fi

    step "Reloading udev rules"
    udevadm control --reload

    if [ -d /sys/class/predator ]; then
        step "Triggering udev for predator subsystem"
        udevadm trigger -s predator
        sleep 0.2  # give udev a moment to apply chgrp/chmod
        local mode_perm
        mode_perm=$(stat -c '%a %G' /sys/class/predator/keyboard0/mode 2>/dev/null || true)
        info "/sys/class/predator/keyboard0/mode  ->  $mode_perm  (want: 664 predator)"
    fi
}

# ---------- manual install ---------------------------------------------------

install_manual() {
    step "Building module against /lib/modules/${KVER}/build"
    make -C "$KERNEL_SRC" clean >/dev/null
    make -C "$KERNEL_SRC"

    # Same orphan-kmod guard as the akmods path — wipe any
    # /lib/modules/.../updates/venator.ko left behind by
    # earlier `make -C kernel install` invocations so depmod picks the
    # extra/ install below (which is what we actually want).
    local mod
    for mod in $(find /lib/modules -type f -name 'venator.ko*' 2>/dev/null); do
        if ! rpm -qf "$mod" >/dev/null 2>&1; then
            step "Removing orphan kmod (not owned by any RPM): $mod"
            rm -f "$mod"
        fi
    done

    if [ "$DO_SIGN" != "no" ]; then
        if ! resolve_signing_keys; then
            cat >&2 <<EOF
${C_RED}xx Can't find a MOK key to sign with.${C_RESET}
   Options:
     - pass --mok-priv PATH --mok-cert PATH
     - install akmods + run install.sh --akmods (it'll generate keys)
     - if SecureBoot is off: install.sh --no-sign
EOF
            exit 1
        fi
        step "Signing with $MOK_PRIV"
        info "(cert: $MOK_CERT)"
        /usr/src/kernels/${KVER}/scripts/sign-file sha256 \
            "$MOK_PRIV" "$MOK_CERT" "$KERNEL_SRC/venator.ko"
    else
        warn "Skipping signing (--no-sign). SecureBoot WILL refuse to load this module."
    fi

    step "Installing to /lib/modules/${KVER}/extra/${PKG_NAME}/"
    # Wipe out any prior install in BOTH extra/ and updates/ so depmod
    # picks our fresh one and modprobe doesn't shadow it with the old
    # extra-installation that's still on disk.
    rm -f "/lib/modules/${KVER}/extra/${PKG_NAME}/venator.ko" \
          "/lib/modules/${KVER}/updates/venator.ko"
    install -Dm644 "$KERNEL_SRC/venator.ko" \
        "/lib/modules/${KVER}/extra/${PKG_NAME}/venator.ko"
    depmod -a "${KVER}"

    install -Dm644 "$REPO_ROOT/modules-load.d/venator.conf" \
        /etc/modules-load.d/venator.conf
    install -Dm644 "$REPO_ROOT/modprobe.d/venator-blacklist.conf" \
        /etc/modprobe.d/venator-blacklist.conf

    # wmbh-probe holds the same WMBH GUID our gaming/lightbar half binds.
    # If it's currently loaded the venator bind silently skips.
    if lsmod | grep -q '^wmbh_probe'; then
        step "Unloading wmbh_probe (it grabs the WMBH GUID first)"
        rmmod wmbh_probe || true
    fi

    if lsmod | grep -q '^venator'; then
        step "Module already loaded; not touching"
    else
        modprobe venator
        step "Module loaded"
    fi
}

# ---------- kernel-install hook install --------------------------------------

# Stage the kernel source tree to /usr/src/venator/ and drop the
# hook to /etc/kernel/install.d/. Then trigger the hook once for the
# running kernel so the user has a loaded module immediately.
#
# This is the "akmods alternative" — same end result (per-kernel rebuild
# + sign + install + depmod), but driven directly by Fedora's
# kernel-install instead of going through akmods.service + an SRPM.
install_kernel_hook() {
    command -v kernel-install >/dev/null 2>&1 || \
        fail "kernel-install not found. This method is Fedora/systemd-only."

    # Signing: reuse the akmods-managed key pair (the hook script looks
    # there too). ensure_akmods_keys generates one if neither exists.
    if [ "$DO_SIGN" != "no" ]; then
        ensure_akmods_keys
    fi

    # 1. Purge any orphan kmod that would shadow the new build. modprobe
    #    searches updates/ before extra/, so a stale `make -C kernel
    #    install` leftover would shadow what the hook produces.
    local mod
    for mod in $(find /lib/modules -type f \
                    \( -name 'venator.ko' \
                       -o -name 'venator.ko.xz' \
                       -o -name 'venator.ko.gz' \
                       -o -name 'venator.ko.zst' \) 2>/dev/null); do
        if ! rpm -qf "$mod" >/dev/null 2>&1; then
            step "Removing orphan kmod (not owned by any RPM): $mod"
            rm -f "$mod"
        fi
    done

    # 2. Stash sources at /usr/src/venator/. The hook reads from
    #    here on every kernel-install add KVER.
    step "Staging sources to /usr/src/${PKG_NAME}/"
    rm -rf "/usr/src/${PKG_NAME}"
    install -d -m755 "/usr/src/${PKG_NAME}"
    install -m644 \
        "$KERNEL_SRC/venator-main.c" \
        "$KERNEL_SRC/venator-battery.c" \
        "$KERNEL_SRC/venator-gaming.c" \
        "$KERNEL_SRC/venator.h" \
        "$KERNEL_SRC/Makefile" \
        "/usr/src/${PKG_NAME}/"

    # 3. Install the hook script.
    step "Installing kernel-install hook to /etc/kernel/install.d/99-${PKG_NAME}.install"
    install -Dm755 "$SCRIPT_DIR/99-${PKG_NAME}.install" \
        "/etc/kernel/install.d/99-${PKG_NAME}.install"

    # 4. Drop the modules-load.d + blacklist entries (same as other methods).
    install -Dm644 "$REPO_ROOT/modules-load.d/venator.conf" \
        /etc/modules-load.d/venator.conf
    install -Dm644 "$REPO_ROOT/modprobe.d/venator-blacklist.conf" \
        /etc/modprobe.d/venator-blacklist.conf

    # 5. Trigger the hook once for the running kernel so the user
    #    doesn't have to wait for the next kernel upgrade to get a
    #    working module. Invoke the script directly rather than `kernel-
    #    install add` so we don't accidentally re-run every other hook
    #    in install.d/ (which can take a while — initrd rebuild etc).
    step "Running hook once for kernel ${KVER}"
    if ! "/etc/kernel/install.d/99-${PKG_NAME}.install" add "${KVER}"; then
        # Hook always exits 0 by design, so this branch shouldn't fire.
        # Treat any non-zero as a bug we want to surface.
        warn "Hook returned non-zero. Check: journalctl -t venator-hook -b"
    fi

    if [ ! -f "/lib/modules/${KVER}/extra/${PKG_NAME}/venator.ko" ]; then
        warn "Hook ran but module wasn't installed. Inspect:"
        warn "    journalctl -t venator-hook -b"
        warn "(common cause: kernel-devel not installed for ${KVER}.)"
    fi

    # 6. Load the new module. Same dance as the other paths.
    if lsmod | grep -q '^wmbh_probe'; then
        step "Unloading wmbh_probe (it grabs the WMBH GUID first)"
        rmmod wmbh_probe || true
    fi
    if lsmod | grep -q '^venator'; then
        step "Reloading venator to pick up the new build"
        rmmod venator || true
    fi
    modprobe venator && step "Module loaded" \
        || warn "modprobe failed. If 'Key was rejected by service' \
appeared: the akmods cert at /etc/pki/akmods/certs/*.der may not be \
enrolled in MOK. Run: sudo mokutil --import /etc/pki/akmods/certs/*.der \
(then reboot to enroll). Or sign the module by hand — see README."
}

# ---------- akmods install ---------------------------------------------------

install_akmods() {
    command -v akmods   >/dev/null || fail "akmods not installed: sudo dnf install akmods"
    command -v rpmbuild >/dev/null || fail "rpm-build not installed: sudo dnf install rpm-build"
    command -v kmodtool >/dev/null || fail "kmodtool not installed (usually pulled in by akmods)"

    [ "$DO_SIGN" != "no" ] && ensure_akmods_keys

    # 0. Purge any unowned venator.ko under /lib/modules/.
    #    modprobe searches updates/ before extra/, so an orphan from a
    #    long-ago `make -C kernel install` can shadow every RPM-installed
    #    .ko on every reinstall and make the user think nothing changed.
    purge_orphan_kos() {
        local mod
        for mod in $(find /lib/modules -type f -name 'venator.ko' \
                                       -o -name 'venator.ko.xz' \
                                       -o -name 'venator.ko.gz' \
                                       -o -name 'venator.ko.zst' \
                     2>/dev/null); do
            if ! rpm -qf "$mod" >/dev/null 2>&1; then
                step "Removing orphan kmod (not owned by any RPM): $mod"
                rm -f "$mod"
            fi
        done
    }
    purge_orphan_kos

    # 1. Build a source tarball akmods expects.
    local staging=/tmp/venator-akmods-build
    rm -rf "$staging"
    mkdir -p "$staging/${PKG_NAME}-${VERSION}"
    cp "$KERNEL_SRC/venator-main.c" \
       "$KERNEL_SRC/venator-battery.c" \
       "$KERNEL_SRC/venator-gaming.c" \
       "$KERNEL_SRC/venator.h" \
       "$KERNEL_SRC/Makefile" \
       "$staging/${PKG_NAME}-${VERSION}/"
    tar -C "$staging" -czf "$staging/${PKG_NAME}-${VERSION}.tar.gz" "${PKG_NAME}-${VERSION}"

    # 2. Build the akmod-* metapackage AND/OR the per-kernel kmod-* via rpmbuild -ba.
    #
    # The spec hard-codes `Release: 1%{?dist}`, which means every rebuild
    # produces RPMs with the same NEVR. `dnf install -y file.rpm` then
    # sees "already installed" and silently skips replacing the binary —
    # so the user thinks the install worked but the kernel module on
    # disk is still the previous build's. We sidestep this by injecting
    # a fresh timestamp into the release tag for every rebuild.
    local rel_stamp
    rel_stamp="1.$(date +%Y%m%d%H%M%S)"
    local top
    top=$(mktemp -d /tmp/predator-rpmbuild.XXXXXX)
    mkdir -p "$top"/{SOURCES,SPECS,SRPMS,BUILD,RPMS}
    cp "$staging/${PKG_NAME}-${VERSION}.tar.gz" "$top/SOURCES/"
    cp "$SCRIPT_DIR/${PKG_NAME}-kmod.spec"      "$top/SPECS/"

    step "Building RPM(s) via kmodtool  (release=${rel_stamp})"
    rpmbuild --define "_topdir $top" \
             --define "_smp_mflags -j1" \
             --define "release_override ${rel_stamp}" \
             -ba "$top/SPECS/${PKG_NAME}-kmod.spec"

    # 3. Stash the SRPM under /usr/src/akmods/ so akmods.service can rebuild
    #    it on the next boot after a kernel upgrade.
    local srpm
    srpm=$(find "$top/SRPMS" -name "${PKG_NAME}-kmod-*.src.rpm" | head -1 || true)
    if [ -n "$srpm" ]; then
        mkdir -p /usr/src/akmods
        install -m644 "$srpm" "/usr/src/akmods/$(basename "$srpm")"
        step "SRPM staged at /usr/src/akmods/$(basename "$srpm")"
    else
        warn "No SRPM produced; auto-rebuild on kernel upgrade won't work."
    fi

    # 4. Find the built artefacts. kmodtool *should* produce
    #    akmod-${PKG_NAME}-*.noarch.rpm + kmod-${PKG_NAME}-*-${KVER}*.rpm,
    #    but on some setups (CachyOS / non-stock kmodtool) we only get the
    #    kmod-*. Either is enough to actually run the module.
    local akmod_rpm kmod_rpm
    akmod_rpm=$(find "$top/RPMS" -name "akmod-${PKG_NAME}-*.noarch.rpm" | head -1 || true)
    kmod_rpm=$(find "$top/RPMS"  -name "kmod-${PKG_NAME}-*-${KVER}*.rpm" | head -1 || true)
    if [ -z "$kmod_rpm" ]; then
        # Fallback: any kmod RPM produced
        kmod_rpm=$(find "$top/RPMS" -name "kmod-${PKG_NAME}-*.rpm" | head -1 || true)
    fi

    # Install policy: always use `rpm -Uvh --force` rather than `dnf
    # install -y`. dnf will SKIP a file.rpm whose NEVR matches what's
    # already installed (true even when the file's actual contents
    # differ), which left the user's old `.ko` on disk after every
    # reinstall. `rpm -U --force` always replaces files regardless of
    # NEVR equality. The dependency resolution we lose by not using dnf
    # doesn't matter here — our RPMs depend only on kernel headers
    # which are already satisfied by the build environment.
    install_rpm_force() {
        local rpmfile="$1"
        step "Installing $(basename "$rpmfile")"
        rpm -Uvh --force --nodeps "$rpmfile"
    }

    if [ -n "$akmod_rpm" ]; then
        install_rpm_force "$akmod_rpm"
        # We always prefer the locally-rpmbuilt kmod (it has the fresh
        # timestamped release tag and matches the .ko we just compiled).
        # akmods --force is still triggered AFTER for the kernel-upgrade
        # auto-rebuild path, but its output is for future boots; for
        # this install we install our own build directly.
        if [ -n "$kmod_rpm" ]; then
            install_rpm_force "$kmod_rpm"
        else
            step "Forcing akmods rebuild for kernel ${KVER}"
            akmods --kernels "${KVER}" --force >/dev/null
            local cached
            cached=$(find /var/cache/akmods -maxdepth 3 \
                      -name "kmod-${PKG_NAME}-*-${KVER}*.rpm" 2>/dev/null \
                      -printf '%T@ %p\n' | sort -rn | head -1 | cut -d' ' -f2-)
            if [ -n "$cached" ]; then
                install_rpm_force "$cached"
            else
                fail "No kmod RPM to install. Check rpmbuild output under $top/RPMS/."
            fi
        fi
        # Refresh akmods state so the auto-rebuild-on-kernel-upgrade
        # pipeline knows about the current SRPM. Failure is non-fatal
        # — the user already has a working kmod on disk.
        akmods --kernels "${KVER}" >/dev/null 2>&1 || true
    elif [ -n "$kmod_rpm" ]; then
        # kmodtool didn't generate the akmod-* metapackage (CachyOS,
        # older kmodtool, etc.). Build our own from
        # packaging/fedora/akmod-venator.spec so future kernel
        # upgrades still get auto-rebuilt by akmods.service.
        step "kmodtool didn't emit akmod-*; building our own metapackage"
        cp "$SCRIPT_DIR/akmod-${PKG_NAME}.spec" "$top/SPECS/"
        if rpmbuild --define "_topdir $top" \
                    -ba "$top/SPECS/akmod-${PKG_NAME}.spec" >/dev/null; then
            akmod_rpm=$(find "$top/RPMS" -name "akmod-${PKG_NAME}-*.noarch.rpm" | head -1 || true)
        fi
        if [ -n "$akmod_rpm" ]; then
            install_rpm_force "$akmod_rpm"
            install_rpm_force "$kmod_rpm"
            akmods --kernels "${KVER}" >/dev/null 2>&1 || true
        else
            warn "Hand-rolled metapackage build failed; falling back to"
            warn "kmod-only install. Auto-rebuild on kernel upgrade will"
            warn "require re-running this script."
            install_rpm_force "$kmod_rpm"
        fi
    else
        fail "Build produced neither akmod-* nor kmod-*. Check $top/RPMS/."
    fi

    # 5. modules-load.d + load now.
    install -Dm644 "$REPO_ROOT/modules-load.d/venator.conf" \
        /etc/modules-load.d/venator.conf
    install -Dm644 "$REPO_ROOT/modprobe.d/venator-blacklist.conf" \
        /etc/modprobe.d/venator-blacklist.conf

    # Second orphan sweep + depmod. We did one at the start; do another
    # here so that if rpm -Uvh somehow left a stale file behind (or the
    # build process dropped one in updates/), it gets cleaned up before
    # modprobe gets to pick a winner.
    purge_orphan_kos
    depmod -a "${KVER}"

    # Always force a reload so the freshly-installed kmod is the one
    # actually running — otherwise the loaded module is the old one
    # and the user thinks the install didn't take.
    if lsmod | grep -q '^venator'; then
        step "Reloading venator to pick up the new build"
        rmmod venator || true
    fi

    # wmbh-probe holds the same WMBH GUID our gaming/lightbar half binds.
    # If it's currently loaded the venator bind silently skips.
    if lsmod | grep -q '^wmbh_probe'; then
        step "Unloading wmbh_probe (it grabs the WMBH GUID first)"
        rmmod wmbh_probe || true
    fi

    modprobe venator && step "Module loaded" \
        || warn "modprobe failed. If 'Key was rejected by service' \
appeared: the akmods cert at /etc/pki/akmods/certs/*.der may not be \
enrolled in MOK. Run: sudo mokutil --import /etc/pki/akmods/certs/*.der \
(then reboot to enroll). Or sign the module by hand — see README."
}

# ---------- run -------------------------------------------------------------

case "$METHOD" in
    manual) install_manual ;;
    akmods) install_akmods ;;
    hook)   install_kernel_hook ;;
    *) usage; exit 2 ;;
esac

setup_group_and_udev

# Auto-enable the restore service for the invoking user so the last-
# applied keyboard + lightbar scheme comes back at next login without
# the user having to know about systemctl. Idempotent — re-running
# the installer is harmless if it's already enabled.
enable_restore_unit() {
    [ -n "$INVOKER" ] || { warn "No SUDO_USER set; skipping restore unit enable"; return; }
    local uid
    uid=$(id -u "$INVOKER" 2>/dev/null) || return
    local rundir="/run/user/$uid"
    if [ ! -d "$rundir" ]; then
        warn "User runtime dir $rundir not present (user not logged in?)"
        warn "Enable manually: systemctl --user enable --now venator-restore"
        return
    fi
    step "Enabling restore + powerwatch user services for $INVOKER"
    # `--user` reads from the invoking user's environment; runuser sets
    # XDG_RUNTIME_DIR + DBUS_SESSION_BUS_ADDRESS for us. powerwatch is
    # what makes the power profile switch in real time on plug/unplug.
    runuser -u "$INVOKER" -- bash -c \
        "export XDG_RUNTIME_DIR=$rundir \
                DBUS_SESSION_BUS_ADDRESS=unix:path=$rundir/bus; \
         systemctl --user daemon-reload && \
         systemctl --user enable --now venator-restore.service && \
         systemctl --user enable --now venator-powerwatch.service" 2>&1 \
        | sed 's/^/    /' \
        || warn "Couldn't auto-enable user services. Run by hand:
        systemctl --user enable --now venator-restore.service
        systemctl --user enable --now venator-powerwatch.service"
}
enable_restore_unit

cat <<EOF

${C_BOLD}Done.${C_RESET}

Verify:
  lsmod | grep predator
  ls /sys/class/predator/keyboard0/
  ls /sys/class/predator/lightbar0/   # (if the gaming/WMBH half bound)

The 'default' profile auto-snapshots every keyboard + lightbar mutation
and is replayed at login via venator-restore.service (enabled
above for $INVOKER if you ran via sudo).

EOF

if [ "$METHOD" = manual ]; then
    info "In --manual mode the module is built only for the CURRENT kernel."
    info "After a kernel upgrade, re-run this script. For automatic rebuilds"
    info "on Fedora, run with --hook (preferred) or --akmods."
fi

if [ "$METHOD" = hook ]; then
    info "Hook installed at /etc/kernel/install.d/99-${PKG_NAME}.install."
    info "Every future kernel upgrade rebuilds the module automatically."
    info "Inspect with: journalctl -t venator-hook -b"
fi
