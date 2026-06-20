#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
#
# venator kernel-module installer.
#
# Default (--auto) detects the OS and runs the right routine:
#
#   Fedora / RHEL-like  -> --hook   : stage sources to /usr/src/venator and
#                                     drop a kernel-install hook so every
#                                     kernel upgrade auto-rebuilds + re-signs.
#   Arch / CachyOS / *  -> --manual : build the module against the running
#                                     kernel (auto LLVM=1 when the kernel is
#                                     clang-built), sign (MOK or sbctl db key,
#                                     auto-detected), install to
#                                     /lib/modules/$(uname -r)/extra/, depmod,
#                                     modprobe. Re-run after a kernel upgrade.
#
# Both end with the module loaded, /etc/modules-load.d/venator.conf in
# place, and signing handled. No RPM / akmods dependency.

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
  --auto     (default)  Detect the OS and pick the routine below:
                          Fedora / RHEL-like  -> --hook
                          Arch / CachyOS / *  -> --manual
  --hook     (Fedora)   Stash sources at /usr/src/venator and drop a
                        kernel-install hook at
                        /etc/kernel/install.d/99-venator.install.
                        Every `kernel-install add` (run automatically by
                        the kernel RPM scriptlets on every upgrade)
                        re-builds + re-signs the module. Then builds now.
  --manual   (Arch/any) Build for the current kernel (auto LLVM=1 when the
                        kernel is clang-built), sign, install to
                        /lib/modules/$(uname -r)/extra/, modules-load.d
                        + modprobe. Re-run after each kernel upgrade.

Secure Boot (signing is OFF by default):
  --secureboot          Sign the module for Secure Boot. Resolves a signing
                        key automatically, in this order:
                          1. /etc/pki/akmods/{private/*.priv,certs/*.der|cer|crt}
                          2. /var/lib/shim-signed/mok/MOK.{priv,der}
                          3. /var/lib/sbctl/keys/db/db.{key,pem}  (sbctl)
                        On Fedora --hook it also generates an akmods key if
                        none exists and prints the mokutil --import line.
  --mok-priv PATH       Explicit signing private key (.priv/.key); implies
                        --secureboot.
  --mok-cert PATH       Explicit signing cert (.der/.cer/.crt/.pem); implies
                        --secureboot.
  --no-sign             Explicitly disable signing (this is the default).

Other:
  --skip-group          Don't create the predator group / set udev perms
  -h, --help            Show this help and exit.

Examples:
  sudo ./install.sh                            # auto-detect OS, no signing
  sudo ./install.sh --secureboot               # auto-detect OS + sign for SB
  sudo ./install.sh --hook --secureboot        # Fedora hook, signed
  sudo ./install.sh --manual                   # build for current kernel, unsigned
  sudo ./install.sh --mok-priv ~/MOK.priv \
                    --mok-cert ~/MOK.der       # sign with explicit keys
EOF
}

METHOD=auto
MOK_PRIV=""
MOK_CERT=""
DO_SIGN=no            # default: non-SecureBoot (don't sign). --secureboot flips it.
DO_GROUP=1

while [ $# -gt 0 ]; do
    case "$1" in
        --auto)       METHOD=auto ;;
        --manual)     METHOD=manual ;;
        --hook)       METHOD=hook ;;
        --secureboot) DO_SIGN=yes ;;
        --mok-priv)   MOK_PRIV="$2"; DO_SIGN=yes; shift ;;
        --mok-cert)   MOK_CERT="$2"; DO_SIGN=yes; shift ;;
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

# ---------- OS detection -----------------------------------------------------

# Echo a coarse OS family: 'fedora' | 'arch' | 'other'. Reads /etc/os-release
# ID first, then ID_LIKE so derivatives resolve correctly (CachyOS / EndeavourOS
# -> arch; Nobara / RHEL / CentOS -> fedora).
detect_os() {
    local id="" like=""
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        id=${ID:-}; like=${ID_LIKE:-}
    fi
    case " $id $like " in
        *" fedora "*|*" rhel "*|*" centos "*) echo fedora ;;
        *" arch "*)                           echo arch ;;
        *)
            # Fall back to marker files if os-release was unhelpful.
            if [ -f /etc/fedora-release ]; then echo fedora
            elif [ -f /etc/arch-release ]; then echo arch
            else echo other; fi ;;
    esac
}

# ---------- signing key resolution -------------------------------------------

# True (0) only if SecureBoot is verifiably ON. Anything else — disabled,
# BIOS/legacy boot, or undeterminable — returns non-zero so we don't force
# signing on systems that don't need it (e.g. CachyOS with SB off, where
# mokutil isn't even installed).
secureboot_enabled() {
    if command -v mokutil >/dev/null 2>&1; then
        mokutil --sb-state 2>/dev/null | grep -qi 'enabled'
        return
    fi
    # No mokutil: read the EFI SecureBoot variable directly. Its value is
    # a 5-byte blob whose last byte is 1 when SecureBoot is enabled.
    local var
    var=$(find /sys/firmware/efi/efivars -maxdepth 1 -name 'SecureBoot-*' 2>/dev/null | head -1)
    [ -n "$var" ] || return 1
    [ "$(od -An -tu1 "$var" 2>/dev/null | tr -s ' ' | sed 's/ $//' | awk '{print $NF}')" = "1" ]
}

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
    # 3. sbctl (Arch / CachyOS). sbctl signs EFI binaries with its `db`
    #    keypair; we reuse that same key/cert to sign the module via
    #    sign-file. Note: the module loads on these systems regardless of
    #    signature (CachyOS doesn't lock down modules under SecureBoot),
    #    but signing with the user's own enrolled db key is the clean path.
    if [ -f /var/lib/sbctl/keys/db/db.key ] && [ -f /var/lib/sbctl/keys/db/db.pem ]; then
        MOK_PRIV=/var/lib/sbctl/keys/db/db.key
        MOK_CERT=/var/lib/sbctl/keys/db/db.pem
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

    # Signing is OFF by default (non-SecureBoot). --secureboot (or explicit
    # --mok-* keys) sets DO_SIGN=yes; only then do we resolve a key and sign.
    if [ "$DO_SIGN" = yes ]; then
        if ! resolve_signing_keys; then
            cat >&2 <<EOF
${C_RED}xx --secureboot was requested but no signing key was found.${C_RESET}
   Options:
     - pass --mok-priv PATH --mok-cert PATH
     - Fedora: run with --hook --secureboot (it generates an akmods-style
               key under /etc/pki/akmods/; enrol it with mokutil --import)
     - Arch/CachyOS: set up sbctl and create keys (sbctl create-keys),
               then re-run; we'll sign with /var/lib/sbctl/keys/db/
EOF
            exit 1
        fi
        step "Signing with $MOK_PRIV"
        info "(cert: $MOK_CERT)"
        # sign-file lives in different places per distro: Fedora ships it
        # under /usr/src/kernels/$KVER/, Arch/CachyOS under the build tree
        # at /lib/modules/$KVER/build/. Pick whichever exists.
        local sign_file=""
        for cand in \
            "/lib/modules/${KVER}/build/scripts/sign-file" \
            "/usr/src/kernels/${KVER}/scripts/sign-file"; do
            [ -x "$cand" ] && { sign_file="$cand"; break; }
        done
        [ -n "$sign_file" ] || \
            fail "sign-file not found under the kernel build tree for ${KVER}. Install kernel headers/devel."
        "$sign_file" sha256 \
            "$MOK_PRIV" "$MOK_CERT" "$KERNEL_SRC/venator.ko"
    elif secureboot_enabled; then
        warn "SecureBoot is ON but signing is disabled (default)."
        warn "The module will likely be rejected at load. Re-run with --secureboot."
    else
        info "Signing disabled (non-SecureBoot mode)."
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

    # Signing is opt-in (--secureboot). When requested, reuse/generate the
    # akmods-managed key pair (the hook script looks there too). Without it
    # the hook builds + installs unsigned, fine on non-SecureBoot systems.
    if [ "$DO_SIGN" = yes ]; then
        ensure_akmods_keys
    elif secureboot_enabled; then
        warn "SecureBoot is ON but signing is disabled (default)."
        warn "The hook will install an unsigned module that won't load."
        warn "Re-run with --secureboot to set up an akmods signing key."
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

# ---------- run -------------------------------------------------------------

# Resolve the OS-specific routine when no method was forced on the CLI.
#   Fedora (+ RHEL-likes)  -> hook   (kernel-install rebuilds on upgrade)
#   Arch / CachyOS / other -> manual (build + sbctl-sign for current kernel)
if [ "$METHOD" = auto ]; then
    case "$(detect_os)" in
        fedora) METHOD=hook ;;
        *)      METHOD=manual ;;
    esac
    step "Detected OS family '$(detect_os)' -> using '$METHOD' method"
fi

case "$METHOD" in
    manual) install_manual ;;
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
    info "Manual mode: the module is built only for the CURRENT kernel."
    info "Re-run this installer after a kernel upgrade. On Fedora, --hook"
    info "rebuilds automatically on every upgrade (a pacman hook for"
    info "Arch/CachyOS is planned)."
fi

if [ "$METHOD" = hook ]; then
    info "Hook installed at /etc/kernel/install.d/99-${PKG_NAME}.install."
    info "Every future kernel upgrade rebuilds the module automatically."
    info "Inspect with: journalctl -t venator-hook -b"
fi

if [ "$DO_SIGN" = yes ]; then
    info "Module signed for Secure Boot."
else
    info "Module NOT signed (non-SecureBoot default). If Secure Boot is on,"
    info "re-run with --secureboot (or: make ... SECUREBOOT=1)."
fi
