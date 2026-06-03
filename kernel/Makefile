# SPDX-License-Identifier: GPL-2.0-only
#
# Out-of-tree build for venator.

obj-m += venator.o
venator-objs := venator-main.o venator-battery.o \
                       venator-gaming.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

install: all
	$(MAKE) -C $(KDIR) M=$(PWD) modules_install
	depmod -a

# Quick reload during development (already built; requires root).
reload:
	-sudo rmmod venator 2>/dev/null || true
	sudo insmod venator.ko
	@echo "Loaded. Watch:  sudo dmesg -w | grep predator"

.PHONY: all clean install reload
