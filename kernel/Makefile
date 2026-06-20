# SPDX-License-Identifier: GPL-2.0-only
#
# Out-of-tree build for venator.

obj-m += venator.o
venator-objs := venator-main.o venator-battery.o \
                       venator-gaming.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

# Auto-detect a Clang/LLVM-built kernel (Arch, CachyOS, and others).
# Building an out-of-tree module with GCC against such a kernel fails:
# kbuild replays the kernel's own clang-only flags (-mllvm,
# -mretpoline-external-thunk, -mstack-alignment=8,
# -fexperimental-late-parse-attributes, -fsplit-lto-unit, ...) which GCC
# rejects outright. When the kernel config says CONFIG_CC_IS_CLANG=y we
# switch the whole build to LLVM=1 so the module is compiled with the
# same toolchain. Override explicitly with `make LLVM=0` (or LLVM=1).
LLVM ?= $(if $(shell grep -sx 'CONFIG_CC_IS_CLANG=y' $(KDIR)/.config),1,)
KBUILD_LLVM := $(if $(LLVM),LLVM=$(LLVM),)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) $(KBUILD_LLVM) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) $(KBUILD_LLVM) clean

install: all
	$(MAKE) -C $(KDIR) M=$(PWD) $(KBUILD_LLVM) modules_install
	depmod -a

# Quick reload during development (already built; requires root).
reload:
	-sudo rmmod venator 2>/dev/null || true
	sudo insmod venator.ko
	@echo "Loaded. Watch:  sudo dmesg -w | grep predator"

.PHONY: all clean install reload
