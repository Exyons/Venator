# SPDX-License-Identifier: GPL-2.0-only
#
# Auto-rebuild metapackage for venator.
#
# This is the akmod-* half. The kmodtool single-spec layout in
# venator-kmod.spec is supposed to emit it, but on some
# setups (CachyOS, older kmodtool) the metapackage subrpm doesn't
# appear, so install.sh builds this hand-rolled fallback instead.
#
# What this package does:
#   - On install, runs akmods against the running kernel so the
#     real kmod gets rebuilt against /usr/src/akmods/predator-
#     sense-kmod-VERSION.src.rpm.
#   - Requires the akmods machinery so dnf pulls it in.
#   - Provides PKG-kmod-common so the per-kernel kmod-PKG-KVER
#     subrpm (which kmodtool DID produce) can install in the same
#     transaction without a missing-dep error.

%global kmod_name venator

# Avoid rpmbuild's reflex of trying to package debugsource files —
# this package has no userspace sources to begin with.
%global debug_package %{nil}

Name:           akmod-%{kmod_name}
Version:        0.1.0
Release:        1%{?dist}
Summary:        Auto-rebuilds the venator kmod on kernel upgrades
License:        GPL-2.0-only
URL:            https://github.com/Exyons/Venator
BuildArch:      noarch

Requires:       akmods
Requires:       %{kmod_name}-kmod-common = %{version}
Provides:       %{kmod_name}-kmod-common = %{version}

%description
Metapackage. Triggers akmods to rebuild the venator kernel
module for the running kernel on install and after every kernel
upgrade. The actual SRPM lives at /usr/src/akmods/, dropped there
by venator's install.sh.

%files
# Intentionally empty -- pure trigger metapackage.

%post
if command -v akmods >/dev/null 2>&1; then
    akmods --kernels "$(uname -r)" --force >/dev/null 2>&1 || :
fi

%changelog
* Sun May 17 2026 Predator-Sense Linux <noreply@github.com> - 0.1.0-1
- Hand-rolled fallback metapackage so akmods rebuilds work on
  CachyOS / other distros where the single-spec kmodtool expansion
  produces no metapackage subrpm.
