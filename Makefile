FILES =									\
	dbus-modbus-client.py						\
	client.py							\
	device.py							\
	devspec.py							\
	mdns.py								\
	probe.py							\
	register.py							\
	scan.py								\
	utils.py							\
	victron_regs.py							\
	vreglink.py							\
	watchdog.py							\

FILES +=								\
	abb.py								\
	carlo_gavazzi.py						\
	comap.py							\
	dse.py								\
	ev_charger.py							\
	smappee.py							\
	victron_em.py							\

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
