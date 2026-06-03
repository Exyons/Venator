# SPDX-License-Identifier: GPL-2.0-only
#
# kmodtool-driven kmod spec for venator.
#
# The kmodtool macro generates the standard akmods/rpmfusion-style
# subpackages from this single spec:
#
#   akmod-venator.noarch         metapackage (depends on the
#                                       SRPM under /usr/src/akmods,
#                                       has %post that triggers akmods)
#   kmod-venator-common          common bits (Provides:
#                                       venator-kmod-common)
#   kmod-venator-<kver>          per-kernel built module
#                                       (only built when rpmbuild is
#                                       invoked with --define "kernels X")
#
# Typical flow on Fedora:
#   rpmbuild -ba this.spec       # produces akmod-* + SRPM
#   dnf install akmod-venator-*.noarch.rpm
#   # %post triggers akmods which rebuilds + signs against
#   # /usr/src/akmods/venator-kmod-*.src.rpm for the current
#   # kernel, drops kmod-venator-<kver>.x86_64.rpm in
#   # /var/cache/akmods.

%global kmod_name venator

# Don't generate -debuginfo or -debugsource subpackages. There are no
# userspace sources here; rpmbuild's debugsource pass otherwise tries
# to package debugsourcefiles.list and fails because we don't ship one.
%global debug_package %{nil}

# akmods passes --define "kernels X X X". Default to current kernel
# when invoked directly without that.
%{!?kernels: %global kernels %(uname -r)}

Name:           %{kmod_name}-kmod
Version:        0.1.0
# install.sh passes --define "release_override 1.YYYYMMDDHHMMSS" so each
# rebuild produces a fresh NEVR; otherwise `dnf install -y file.rpm`
# would skip with "already installed" and leave the stale binary in
# place. Standalone rpmbuild (no override) falls back to the static 1.
Release:        %{?release_override}%{!?release_override:1}%{?dist}
Summary:        Kernel module for the Acer Predator Helios 16 PH16-71 RGB keyboard
License:        GPL-2.0-only
URL:            https://github.com/Exyons/Venator

Source0:        %{kmod_name}-%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  kmodtool
# kernel-devel for at least one kernel must be present for the per-kernel
# subpackage's build to succeed. We deliberately don't pin a version --
# CachyOS and other non-stock kernels ship kernel-devel under different
# names but with /lib/modules/<kver>/build pointing at the right place.
ExclusiveArch:  x86_64

# kmodtool generates the akmod-<name> and kmod-<name>-<kver> subpackages
# from this expansion. --akmod gives us the metapackage that triggers
# akmods.
%{expand:%(kmodtool --target %{_target_cpu} --kmodname %{kmod_name} --akmod %{?kernels:--for-kernels "%{?kernels}"} 2>/dev/null)}

%description
Out-of-tree kernel module that binds the Chicony 04F2:0117 vendor HID
interface (mi_03 / FF02 vendor usage page) on the Acer Predator Helios
16 PH16-71 keyboard MCU and exposes /sys/class/predator/keyboardN/ for
LED control from userspace.

This is the SRPM. Install akmod-venator to have akmods rebuild
the kernel module on every kernel upgrade.

Project: %{url}

%prep
%autosetup -n %{kmod_name}-%{version}

%build
# Build in place per kernel and stash the .ko OUTSIDE the source dir
# (via ../) so the subsequent `make clean` between kernels doesn't wipe
# the renamed .ko along with the build artefacts. akmods invokes
# rpmbuild once per kernel anyway, so the loop almost always has
# exactly one iteration.
for kernel_version in %{?kernel_versions}; do
    kver=${kernel_version%%___*}
    ksrc=${kernel_version##*___}
    %{__make} -C "$ksrc" %{?_smp_mflags} M=$PWD modules
    %{__mv} venator.ko ../venator.ko.${kver}
    %{__make} -C "$ksrc" M=$PWD clean
done

%install
for kernel_version in %{?kernel_versions}; do
    kver=${kernel_version%%___*}
    %{__install} -d %{buildroot}%{kmodinstdir_prefix}/${kver}/%{kmodinstdir_postfix}/
    %{__install} -p -m 0644 ../venator.ko.${kver} \
        %{buildroot}%{kmodinstdir_prefix}/${kver}/%{kmodinstdir_postfix}/venator.ko
done

%clean
rm -rf %{buildroot}

%changelog
* Fri May 15 2026 Predator-Sense Linux <noreply@github.com> - 0.1.0-1
- kmodtool-driven spec for proper akmods integration.
- Build in place + rename .ko per kernel (avoids the `cp -a .`
  self-recursion failure in the previous draft).

