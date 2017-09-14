
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software # Foundation, either version 2 of the License, or
# (at your option) any later version.

INITSYS :=  $(shell if [ -f /usr/bin/systemctl ]; then echo "systemd"; else echo "sysvinit"; fi)
DEPCMD  :=  $(shell if [ -f /usr/bin/dnf ]; then echo "dnf builddep"; else echo "yum-builddep"; fi)

SUBDIRS := Common Client documentation
ifdef WITH_SERVER
    SUBDIRS += Server
endif
ifdef WITH_LABCONTROLLER
    SUBDIRS += LabController
endif
ifdef WITH_INTTESTS
    SUBDIRS += IntegrationTests
endif

.PHONY: build
build: setup
	set -e; for i in $(SUBDIRS); do $(MAKE) INITSYS=$(INITSYS) -C $$i build; done

.PHONY: install
install:
	set -e; for i in $(SUBDIRS); do $(MAKE) INITSYS=$(INITSYS) -C $$i install; done

.PHONY: clean
clean:
	set -e; for i in $(SUBDIRS); do $(MAKE) INITSYS=$(INITSYS) -C $$i clean; done

.PHONY: check
check:
	set -e; for i in $(SUBDIRS); do $(MAKE) INITSYS=$(INITSYS) -C $$i check; done

.PHONY: devel
devel: build
	set -e; for i in $(SUBDIRS); do $(MAKE) INITSYS=$(INITSYS) -C $$i devel; done

.PHONY: setup
setup:
	sudo $(DEPCMD) -y beaker.spec

submods:
	git submodules init
	git submodules update
