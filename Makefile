FILES =									\
	dbus-modbus-client.py						\
	abb.py								\
	carlo_gavazzi.py						\
	client.py							\
	comap.py							\
	device.py							\
	devspec.py							\
	ev_charger.py							\
	mdns.py								\
	probe.py							\
	register.py							\
	scan.py								\
	smappee.py							\
	utils.py							\
	victron_regs.py							\
	vreglink.py							\
	watchdog.py							\

VELIB =									\
	settingsdevice.py						\
	ve_utils.py							\
	vedbus.py							\

all:

install:
	install -d $(DESTDIR)$(bindir)
	install -m 0644 $(FILES) $(DESTDIR)$(bindir)
	install -m 0644 $(addprefix ext/velib_python/,$(VELIB)) \
		$(DESTDIR)$(bindir)
	chmod +x $(DESTDIR)$(bindir)/$(firstword $(FILES))

clean:
