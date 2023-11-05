#! /usr/bin/python3 -u

from argparse import ArgumentParser
import dbus
import dbus.mainloop.glib
import faulthandler
from functools import partial
import os
import pymodbus.constants
from settingsdevice import SettingsDevice
import signal
import time
import traceback
from vedbus import VeDbusService
from gi.repository import GLib

import device
import devspec
import mdns
import probe
from scan import *
from utils import *
import watchdog

import carlo_gavazzi
import dse
import ev_charger
import smappee
import abb
import comap
import victron_em
import generic_modbus_meter

import logging
log = logging.getLogger()

NAME = os.path.basename(__file__)
VERSION = '1.42'

__all__ = ['NAME', 'VERSION']

pymodbus.constants.Defaults.Timeout = 0.5

MODBUS_TCP_PORT = 502

MAX_ERRORS = 5
FAILED_INTERVAL = 10
MDNS_CHECK_INTERVAL = 5
MDNS_QUERY_INTERVAL = 60
SCAN_INTERVAL = 600
UPDATE_INTERVAL = 100

if_blacklist = [
    'ap0',
]

def percent(path, val):
    return '%d%%' % val

class Client:
    def __init__(self, name):
        self.name = name
        self.devices = []
        self.failed = []
        self.failed_time = 0
        self.scanner = None
        self.scan_time = time.time()
        self.auto_scan = False
        self.err_exit = False
        self.keep_failed = True
        self.svc = None
        self.watchdog = watchdog.Watchdog()

    def start_scan(self, full=False):
        if self.scanner:
            return

        log.info('Starting background scan')

        s = self.new_scanner(full)

        if s.start():
            self.scanner = s

    def stop_scan(self):
        if self.scanner:
            self.scanner.stop()

    def scan_update(self):
        devices = self.scanner.get_devices()

        for d in devices:
            if d in self.devices:
                d.destroy()
                continue

            try:
                self.init_device(d, False)
                self.devices.append(d)
            except:
                log.info('Error initialising %s, skipping', d)
                traceback.print_exc()

        self.save_devices()

    def scan_complete(self):
        self.scan_time = time.time()

        if not self.devices and self.err_exit:
            os._exit(1)

    def set_scan(self, path, val):
        if val:
            self.start_scan()
        else:
            self.stop_scan()

        return True

    def init_device(self, dev, nosave=False, enable=True):
        dev.init(self.dbusconn, enable)
        dev.nosave = nosave

    def del_device(self, dev):
        self.devices.remove(dev)
        dev.destroy()

    def update_device(self, dev):
        try:
            dev.update()
            dev.err_count = 0
        except:
            dev.err_count += 1
            if dev.err_count == MAX_ERRORS:
                log.info('Device %s failed', dev)
                if self.err_exit:
                    os._exit(1)
                if not dev.nosave:
                    self.failed.append(dev.spec)
                self.del_device(dev)

    def probe_filter(self, dev):
        return dev not in self.devices

    def probe_devices(self, devlist, nosave=False, enable=True):
        devs = set(devlist) - set(self.devices)
        devs, failed = probe.probe(devs, filt=self.probe_filter)

        for d in devs:
            try:
                self.init_device(d, nosave, enable)
                self.devices.append(d)
            except:
                failed.append(d.spec)
                d.destroy()

        return failed

    def save_devices(self):
        devs = list(filter(lambda d: not d.nosave, self.devices))
        devstr = ','.join(sorted(map(str, devs + self.failed)))
        if devstr != self.settings['devices']:
            self.settings['devices'] = devstr

    def update_devlist(self, old, new):
        old = devspec.fromstrings(filter(None, old.split(',')))
        new = devspec.fromstrings(filter(None, new.split(',')))
        cur = set(self.devices)
        rem = old - new

        for d in rem & cur:
            dd = self.devices[self.devices.index(d)]
            self.del_device(dd)

        self.failed = self.probe_devices(new);
        self.save_devices()

    def setting_changed(self, name, old, new):
        if name == 'devices':
            self.update_devlist(old, new)
            return

    def init_settings(self):
        settings_path = '/Settings/ModbusClient/' + self.name
        SETTINGS = {
            'devices':  [settings_path + '/Devices', '', 0, 0],
            'autoscan': [settings_path + '/AutoScan', self.auto_scan, 0, 1],
        }

        self.dbusconn = private_bus()

        log.info('Waiting for localsettings')
        self.settings = SettingsDevice(self.dbusconn, SETTINGS,
                                       self.setting_changed, timeout=10)

    def init_devices(self, force_scan):
        self.update_devlist('', self.settings['devices'])

        if not self.keep_failed:
            self.failed = []

        scan = force_scan

        if not self.devices or self.failed:
            if self.settings['autoscan']:
                scan = True

        if scan:
            self.start_scan(force_scan)

        self.watchdog.start()

    def init(self, force_scan):
        self.init_settings()
        self.init_devices(force_scan)

    def update(self):
        if self.scanner:
            if self.svc:
                self.svc['/Scan'] = self.scanner.running
                self.svc['/ScanProgress'] = \
                    100 * self.scanner.done / self.scanner.total

            self.scan_update()

            if not self.scanner.running:
                self.scan_complete()
                self.scanner = None
                if self.svc:
                    self.svc['/ScanProgress'] = None

        for d in self.devices:
            self.update_device(d)

        if self.failed:
            now = time.time()

            if now - self.failed_time > FAILED_INTERVAL:
                self.failed = self.probe_devices(self.failed)
                self.failed_time = now

            if self.settings['autoscan']:
                if now - self.scan_time > SCAN_INTERVAL:
                    self.start_scan()

        self.watchdog.update()

    def update_timer(self):
        try:
            self.update()
        except:
            log.error('Uncaught exception in update')
            traceback.print_exc()

        return True

class NetClient(Client):
    def __init__(self):
        super().__init__('tcp')

    def new_scanner(self, full):
        return NetScanner(MODBUS_TCP_PORT, if_blacklist)

    def init_settings(self):
        super().init_settings()

        svcname = 'com.victronenergy.modbusclient.%s' % self.name
        self.svc = VeDbusService(svcname, self.dbusconn)
        self.svc.add_path('/Scan', False, writeable=True,
                          onchangecallback=self.set_scan)
        self.svc.add_path('/ScanProgress', None, gettextcallback=percent)

    def init(self, *args):
        super().init(*args)

        self.mdns = mdns.MDNS()
        self.mdns.start()
        self.mdns_check_time = 0
        self.mdns_query_time = 0

    def update(self):
        super().update()

        now = time.time()

        if now - self.mdns_query_time > MDNS_QUERY_INTERVAL:
            self.mdns_query_time = now
            self.mdns.req()

        if now - self.mdns_check_time > MDNS_CHECK_INTERVAL:
            self.mdns_check_time = now
            maddr = self.mdns.get_devices()
            if maddr:
                self.probe_devices(maddr, nosave=True, enable=False)

    def init_device(self, dev, *args):
        super().init_device(dev, *args)

        if dev.nosave:
            dev_path = '/Devices/' + dev.get_ident()
            with self.svc as s:
                s.add_path(dev_path + '/Enabled', int(dev.enabled),
                           writeable=True,
                           onchangecallback=partial(self.enable_device, dev))
                s.add_path(dev_path + '/Serial', dev.info['/Serial'])
                name = str(dev.info['/CustomName']) or dev.productname
                s.add_path(dev_path + '/Name', name)

    def del_device(self, dev):
        with self.svc as s:
            s.del_tree('/Devices/' + dev.get_ident())
        super().del_device(dev)

    def enable_device(self, dev, path, val):
        dev.set_enabled(bool(val))
        return True

class SerialClient(Client):
    def __init__(self, tty, rate, mode):
        super().__init__(tty)
        self.tty = tty
        self.rate = rate
        self.mode = mode
        self.auto_scan = True
        self.keep_failed = False

    def new_scanner(self, full):
        return SerialScanner(self.tty, self.rate, self.mode, full=full)

def main():
    parser = ArgumentParser(add_help=True)
    parser.add_argument('-d', '--debug', help='enable debug logging',
                        action='store_true')
    parser.add_argument('-f', '--force-scan', action='store_true')
    parser.add_argument('-m', '--mode', choices=['ascii', 'rtu'], default='rtu')
    parser.add_argument('-r', '--rate', type=int, action='append')
    parser.add_argument('-s', '--serial')
    parser.add_argument('-x', '--exit', action='store_true',
                        help='exit on error')

    args = parser.parse_args()

    logging.basicConfig(format='%(levelname)-8s %(message)s',
                        level=(logging.DEBUG if args.debug else logging.INFO))

    logging.getLogger('pymodbus.client.sync').setLevel(logging.CRITICAL)

    signal.signal(signal.SIGINT, lambda s, f: os._exit(1))
    faulthandler.register(signal.SIGUSR1)
    faulthandler.enable()

    dbus.mainloop.glib.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()

    if args.serial:
        tty = os.path.basename(args.serial)
        client = SerialClient(tty, args.rate, args.mode)
    else:
        client = NetClient()

    client.err_exit = args.exit
    client.init(args.force_scan)

    GLib.timeout_add(UPDATE_INTERVAL, client.update_timer)
    mainloop.run()

if __name__ == '__main__':
    main()
