# SPDX-License-Identifier: GPL-2.0-only
#
# Top-level make for the userspace half of venator.
# The kernel module has its own Makefile under kernel/, plus a
# Fedora akmods packaging flow under packaging/fedora/.
#
# Targets:
#   make install         install CLI + udev rule + systemd unit + modules-load
#   make uninstall       reverse the above
#   make hook-install    Fedora kernel-install hook (recommended)
#   make akmods-install  legacy akmods path (still works)
#   make manual-install  one-shot build for the current kernel
#   make help            show this
#
# Install root knobs (defaults match /usr/local hierarchy):
#   PREFIX=/usr/local           (--> $PREFIX/bin, $PREFIX/share/venator)
#   DESTDIR=                    (for staged installs; rpm/deb packaging)
#   UDEVDIR=/etc/udev/rules.d
#   SYSTEMD_USER_DIR=/etc/systemd/user
#   MODULES_LOAD_DIR=/etc/modules-load.d

PREFIX           ?= /usr/local
DESTDIR          ?=
BINDIR           := $(PREFIX)/bin
SHAREDIR         := $(PREFIX)/share/venator
UDEVDIR          ?= /etc/udev/rules.d
SYSTEMD_USER_DIR   ?= /etc/systemd/user
SYSTEMD_SYSTEM_DIR ?= /etc/systemd/system
MODULES_LOAD_DIR ?= /etc/modules-load.d

CLI_SRC          := cli/venator
ASSET_DIRS       := animations designs keymaps
UDEV_RULE        := udev/70-venator.rules
SYSTEMD_UNIT     := systemd/venator-restore.service
SYSTEMD_WATCH_UNIT := systemd/venator-powerwatch.service
SYSTEMD_PERMS_UNIT := systemd/venator-perms.service
MODULES_LOAD_CONF := modules-load.d/venator.conf

# GUI bits. The TUI is now invoked via the `venator tui`
# subcommand of the main CLI; the standalone `venator-tui`
# launcher was retired in favour of that single entry point.
GUI_DIR          := gui

# ANSI colour escapes for printf'd help / status output. Single-quoted
# in recipes so $(VAR) expands at make-time and printf interprets the
# escape itself. Set NO_COLOR=1 to suppress (see https://no-color.org).
ifeq ($(NO_COLOR),)
G  := \033[0;32m
Y  := \033[1;33m
R  := \033[0;31m
B  := \033[1m
D  := \033[2m
N  := \033[0m
endif

.PHONY: all install uninstall purge help akmods-install akmods-uninstall manual-install hook-install

all: help

help:
	@printf '$(B)venator -- install targets$(N)\n\n'
	@printf '$(B)Install:$(N)\n'
	@printf '  $(G)sudo make hook-install$(N)     [Fedora, recommended] drop a kernel-install hook\n'
	@printf '                            so every kernel upgrade auto-rebuilds + re-signs.\n'
	@printf '                            No akmods/rpm-build dependency, no daemon.\n'
	@printf '  $(G)sudo make akmods-install$(N)   [Fedora] same end result via akmods.service.\n'
	@printf '                            Requires akmods, kmodtool, rpm-build. Kept as a\n'
	@printf '                            fallback if hook-install doesn'\''t suit you.\n'
	@printf '  $(G)sudo make manual-install$(N)   Any distro / kernel. Build, sign, install the\n'
	@printf '                            kmod for the current kernel. Re-run after each\n'
	@printf '                            kernel upgrade.\n'
	@printf '  $(G)sudo make install$(N)          Userspace only (CLI / assets / udev / systemd /\n'
	@printf '                            modules-load.d). Doesn'\''t build the kernel module.\n'
	@printf '                            All *-install targets above include this.\n\n'
	@printf '$(B)Uninstall:$(N)\n'
	@printf '  $(G)sudo make uninstall$(N)        Remove EVERYTHING (kmod, RPM, userspace,\n'
	@printf '                            modules-load.d, systemd unit + its enable). Leaves\n'
	@printf '                            per-user data under ~/.config/venator/ alone.\n'
	@printf '  $(G)sudo make purge$(N)            Like uninstall + nuke ~/.config/venator/\n'
	@printf '                            and ~/.cache/venator/ for the invoking user.\n\n'
	@printf '$(B)Install paths:$(N)\n'
	@printf '  PREFIX            = $(PREFIX)\n'
	@printf '  DESTDIR           = $(DESTDIR)\n'
	@printf '  BINDIR            = $(DESTDIR)$(BINDIR)\n'
	@printf '  SHAREDIR          = $(DESTDIR)$(SHAREDIR)\n'
	@printf '  UDEVDIR           = $(DESTDIR)$(UDEVDIR)\n'
	@printf '  SYSTEMD_USER_DIR  = $(DESTDIR)$(SYSTEMD_USER_DIR)\n'
	@printf '  MODULES_LOAD_DIR  = $(DESTDIR)$(MODULES_LOAD_DIR)\n'

install:
	@printf '$(G)==>$(N) Installing CLI to $(DESTDIR)$(BINDIR)/venator\n'
	@install -Dm755 $(CLI_SRC) $(DESTDIR)$(BINDIR)/venator
	@for d in $(ASSET_DIRS); do \
	    if [ -d cli/$$d ]; then \
	        printf '$(G)==>$(N) Installing %s/ to %s/\n' "$$d" "$(DESTDIR)$(SHAREDIR)/$$d"; \
	        find cli/$$d -type f \( -name '*.py' -o -name '*.json' -o -name '*.md' \) \
	            -printf '%P\n' \
	            | while IFS= read -r rel; do \
	                install -Dm644 cli/$$d/$$rel $(DESTDIR)$(SHAREDIR)/$$d/$$rel; \
	            done; \
	    fi; \
	done
	@printf '$(G)==>$(N) Installing udev rule to $(DESTDIR)$(UDEVDIR)/$(notdir $(UDEV_RULE))\n'
	@install -Dm644 $(UDEV_RULE) $(DESTDIR)$(UDEVDIR)/$(notdir $(UDEV_RULE))
	@printf '$(G)==>$(N) Installing systemd unit to $(DESTDIR)$(SYSTEMD_USER_DIR)/$(notdir $(SYSTEMD_UNIT))\n'
	@install -Dm644 $(SYSTEMD_UNIT) $(DESTDIR)$(SYSTEMD_USER_DIR)/$(notdir $(SYSTEMD_UNIT))
	@printf '$(G)==>$(N) Installing systemd unit to $(DESTDIR)$(SYSTEMD_USER_DIR)/$(notdir $(SYSTEMD_WATCH_UNIT))\n'
	@install -Dm644 $(SYSTEMD_WATCH_UNIT) $(DESTDIR)$(SYSTEMD_USER_DIR)/$(notdir $(SYSTEMD_WATCH_UNIT))
	@printf '$(G)==>$(N) Installing systemd perms unit to $(DESTDIR)$(SYSTEMD_SYSTEM_DIR)/$(notdir $(SYSTEMD_PERMS_UNIT))\n'
	@install -Dm644 $(SYSTEMD_PERMS_UNIT) $(DESTDIR)$(SYSTEMD_SYSTEM_DIR)/$(notdir $(SYSTEMD_PERMS_UNIT))
	@# Enable the system-wide perms unit so platform_profile + battery
	@# threshold writes don't need sudo for users in the predator group.
	@if [ -z "$(DESTDIR)" ] && command -v systemctl >/dev/null 2>&1; then \
	    systemctl daemon-reload 2>/dev/null || true; \
	    systemctl enable --now venator-perms.service 2>/dev/null || \
	        printf '$(Y)note:$(N) `systemctl enable --now venator-perms.service` failed; run it manually if you want passwordless `power` / `battery limit`.\n'; \
	fi
	@printf '$(G)==>$(N) Installing modules-load.d entry to $(DESTDIR)$(MODULES_LOAD_DIR)/$(notdir $(MODULES_LOAD_CONF))\n'
	@install -Dm644 $(MODULES_LOAD_CONF) $(DESTDIR)$(MODULES_LOAD_DIR)/$(notdir $(MODULES_LOAD_CONF))
	@# GUI: client library + TUI .py modules to $(SHAREDIR)/gui/.
	@# The TUI is invoked via `venator tui` (no separate binary).
	@if [ -d $(GUI_DIR) ]; then \
	    printf '$(G)==>$(N) Installing GUI to %s/gui/\n' "$(DESTDIR)$(SHAREDIR)"; \
	    mkdir -p $(DESTDIR)$(SHAREDIR)/gui; \
	    find $(GUI_DIR) -maxdepth 1 -type f \( -name '*.py' -o -name '*.md' -o -name '*.tcss' \) \
	        -exec install -m644 -t $(DESTDIR)$(SHAREDIR)/gui {} + ; \
	fi
	@# Clean up any old standalone launcher from previous installs.
	@rm -f $(DESTDIR)$(BINDIR)/venator-tui
	@# Seed the per-user keymap so per-key painting works out of the box.
	@# Non-destructive (skip if one already exists) and only on a real,
	@# non-staged install. Resolves the invoking user even under sudo.
	@if [ -z "$(DESTDIR)" ] && [ -f cli/keymaps/ph16-71.json ]; then \
	    U="$${SUDO_USER:-$$USER}"; \
	    H="$$(getent passwd "$$U" | cut -d: -f6)"; \
	    if [ -n "$$H" ]; then \
	        KM="$$H/.config/venator/keymap.json"; \
	        if [ -f "$$KM" ]; then \
	            printf '$(G)==>$(N) Keymap already present at %s (left as-is)\n' "$$KM"; \
	        else \
	            printf '$(G)==>$(N) Installing default PH16-71 keymap to %s\n' "$$KM"; \
	            install -d -m755 "$$H/.config/venator" && \
	            install -m644 cli/keymaps/ph16-71.json "$$KM" && \
	            chown -R "$$U" "$$H/.config/venator" 2>/dev/null || true; \
	        fi; \
	    fi; \
	fi
	@# Brief; the comprehensive "Done -- here's what to do next" summary
	@# is printed by packaging/fedora/install.sh at the very end so
	@# manual-install / akmods-install give the user a single block of
	@# instructions at the bottom of their terminal. Running `make
	@# install` alone is supported but uncommon; tell them what to do.
	@printf '\n$(B)Userspace installed.$(N) '
	@printf 'For the kernel module + group setup, run one of:\n'
	@printf '  $(G)sudo make hook-install$(N)     $(D)# Fedora; recommended$(N)\n'
	@printf '  $(G)sudo make akmods-install$(N)   $(D)# Fedora via akmods; legacy/fallback$(N)\n'
	@printf '  $(G)sudo make manual-install$(N)   $(D)# any distro; re-run after kernel upgrades$(N)\n'

uninstall:
	@# Stop and disable the systemd user unit for the invoking user.
	@if [ -n "$$SUDO_USER" ]; then \
	    UID_=$$(id -u "$$SUDO_USER" 2>/dev/null); \
	    HOME_=$$(getent passwd "$$SUDO_USER" | cut -d: -f6); \
	    if [ -n "$$UID_" ] && [ -S "/run/user/$$UID_/bus" ]; then \
	        printf '$(G)==>$(N) Stopping + disabling user units for %s\n' "$$SUDO_USER"; \
	        sudo -u "$$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$$UID_" \
	            systemctl --user disable --now venator-restore 2>/dev/null || true; \
	        sudo -u "$$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$$UID_" \
	            systemctl --user disable --now venator-powerwatch 2>/dev/null || true; \
	    fi; \
	    if [ -n "$$HOME_" ]; then \
	        rm -f "$$HOME_/.config/systemd/user/default.target.wants/venator-restore.service"; \
	        rm -f "$$HOME_/.config/systemd/user/default.target.wants/venator-powerwatch.service"; \
	        if [ -f "$$HOME_/.cache/venator/background.pid" ]; then \
	            printf '$(G)==>$(N) Killing background worker\n'; \
	            kill "$$(cat $$HOME_/.cache/venator/background.pid)" 2>/dev/null || true; \
	            rm -f "$$HOME_/.cache/venator/background.pid"; \
	        fi; \
	    fi; \
	fi
	@# rmmod the kernel module if loaded.
	@if lsmod 2>/dev/null | grep -q '^venator'; then \
	    printf '$(G)==>$(N) Removing kernel module\n'; \
	    rmmod venator 2>/dev/null || rmmod venator 2>/dev/null || true; \
	fi
	@# dnf-remove the kmod RPM and the akmod-* metapackage (if any), and
	@# clear the staged SRPM so akmods.service won't try to rebuild later.
	@if rpm -q kmod-venator >/dev/null 2>&1 || \
	    rpm -qa 2>/dev/null | grep -q '^kmod-venator-'; then \
	    printf '$(G)==>$(N) Removing kmod RPM(s)\n'; \
	    dnf remove -y akmod-venator 'kmod-venator*' 2>/dev/null || \
	        rpm -e --nodeps $$(rpm -qa 2>/dev/null | grep '^kmod-venator\|^akmod-venator') 2>/dev/null || true; \
	fi
	@rm -f /usr/src/akmods/venator-kmod-*.src.rpm 2>/dev/null
	@# Tear down the kernel-install hook + staged sources (hook-install path).
	@if [ -e /etc/kernel/install.d/99-venator.install ]; then \
	    printf '$(G)==>$(N) Removing /etc/kernel/install.d/99-venator.install\n'; \
	    rm -f /etc/kernel/install.d/99-venator.install; \
	fi
	@if [ -d /usr/src/venator ]; then \
	    printf '$(G)==>$(N) Removing /usr/src/venator\n'; \
	    rm -rf /usr/src/venator; \
	fi
	@# Drop kernel-install-installed .ko under /lib/modules/*/extra/venator.
	@find /lib/modules -maxdepth 3 -type d -name venator -path '*/extra/venator' \
	    -exec rm -rf {} + 2>/dev/null || true
	@# Remove userspace files.
	@printf '$(G)==>$(N) Removing $(DESTDIR)$(BINDIR)/venator\n'
	@rm -f  $(DESTDIR)$(BINDIR)/venator
	@printf '$(G)==>$(N) Removing $(DESTDIR)$(SHAREDIR)\n'
	@rm -rf $(DESTDIR)$(SHAREDIR)
	@printf '$(G)==>$(N) Removing $(DESTDIR)$(UDEVDIR)/$(notdir $(UDEV_RULE))\n'
	@rm -f  $(DESTDIR)$(UDEVDIR)/$(notdir $(UDEV_RULE))
	@printf '$(G)==>$(N) Removing $(DESTDIR)$(SYSTEMD_USER_DIR)/$(notdir $(SYSTEMD_UNIT))\n'
	@rm -f  $(DESTDIR)$(SYSTEMD_USER_DIR)/$(notdir $(SYSTEMD_UNIT))
	@printf '$(G)==>$(N) Removing $(DESTDIR)$(SYSTEMD_USER_DIR)/$(notdir $(SYSTEMD_WATCH_UNIT))\n'
	@rm -f  $(DESTDIR)$(SYSTEMD_USER_DIR)/$(notdir $(SYSTEMD_WATCH_UNIT))
	@if [ -z "$(DESTDIR)" ] && command -v systemctl >/dev/null 2>&1; then \
	    systemctl disable --now venator-perms.service 2>/dev/null || true; \
	fi
	@printf '$(G)==>$(N) Removing $(DESTDIR)$(SYSTEMD_SYSTEM_DIR)/$(notdir $(SYSTEMD_PERMS_UNIT))\n'
	@rm -f  $(DESTDIR)$(SYSTEMD_SYSTEM_DIR)/$(notdir $(SYSTEMD_PERMS_UNIT))
	@printf '$(G)==>$(N) Removing $(DESTDIR)$(MODULES_LOAD_DIR)/$(notdir $(MODULES_LOAD_CONF))\n'
	@rm -f  $(DESTDIR)$(MODULES_LOAD_DIR)/$(notdir $(MODULES_LOAD_CONF))
	@printf '$(G)==>$(N) Removing GUI launcher + files\n'
	@rm -f  $(DESTDIR)$(BINDIR)/venator-tui
	@rm -rf $(DESTDIR)$(SHAREDIR)/gui
	@udevadm control --reload 2>/dev/null || true
	@printf '\n$(B)Uninstalled.$(N)\n'
	@printf '  $(D)Per-user data left alone: ~/.config/venator/ (profiles,$(N)\n'
	@printf '  $(D)keymap, custom designs/animations) and ~/.cache/venator/.$(N)\n'
	@printf '  $(D)akmods signing keys at /etc/pki/akmods/ left in place.$(N)\n'

hook-install: install
	@if [ "$$EUID" -ne 0 ]; then \
	    echo "hook-install must be run as root (sudo make hook-install)"; \
	    exit 1; \
	fi
	packaging/fedora/install.sh --hook

akmods-install: install
	@if [ "$$EUID" -ne 0 ]; then \
	    echo "akmods-install must be run as root (sudo make akmods-install)"; \
	    exit 1; \
	fi
	packaging/fedora/install.sh --akmods

manual-install: install
	@if [ "$$EUID" -ne 0 ]; then \
	    echo "manual-install must be run as root (sudo make manual-install)"; \
	    exit 1; \
	fi
	packaging/fedora/install.sh --manual

akmods-uninstall: uninstall
	@# Back-compat alias. `make uninstall` already does the kernel-side
	@# removal as well, so this just chains.

purge: uninstall
	@# uninstall + nuke per-user data. Useful for clean reinstalls.
	@if [ -n "$$SUDO_USER" ]; then \
	    HOME_=$$(getent passwd "$$SUDO_USER" | cut -d: -f6); \
	    if [ -n "$$HOME_" ]; then \
	        printf '$(G)==>$(N) Removing %s/.config/venator and %s/.cache/venator\n' "$$HOME_" "$$HOME_"; \
	        rm -rf "$$HOME_/.config/venator" "$$HOME_/.cache/venator"; \
	    fi; \
	fi
