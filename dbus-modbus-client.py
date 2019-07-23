#! /usr/bin/python -u

from argparse import ArgumentParser
import dbus
import dbus.mainloop.glib
import gobject
import os
import pymodbus.constants
from settingsdevice import SettingsDevice
import traceback
from vedbus import VeDbusService

import device
from scan import *
from utils import *

import carlo_gavazzi

import logging
log = logging.getLogger()

NAME = os.path.basename(__file__)
VERSION = '0.1'

__all__ = ['NAME', 'VERSION']

pymodbus.constants.Defaults.Timeout = 0.5

MODBUS_PORT = 502
MODBUS_UNIT = 1

MAX_ERRORS = 5

SETTINGS = {
    'devices': ['/Settings/ModbusClient/Devices', '', 0, 0],
}

if_blacklist = [
    'ap0',
]

devices = []
failed = []
scanner = None

def start_scan():
    global scanner

    if scanner:
        return

    log.info('Starting background scan')

    s = NetScanner('tcp', MODBUS_PORT, MODBUS_UNIT, if_blacklist)

    if s.start():
        scanner = s

def stop_scan():
    if scanner:
        scanner.stop()

def scan_complete():
    global settings

    for d in scanner.devices:
        if d in devices:
            continue

        try:
            d.init(settings)
            devices.append(d)
        except:
            log.info('Error initialising %d, skipping' % d)
            traceback.print_exc()

    settings['devices'] = ','.join([str(d) for d in devices])

def set_scan(path, val):
    if val:
        start_scan()
    else:
        stop_scan()

    return True

def update_device(dev):
    try:
        dev.update()
        dev.err_count = 0
    except:
        dev.err_count += 1
        if dev.err_count == MAX_ERRORS:
            devices.remove(dev)
            failed.append(str(dev))
            dev.__del__()

def init_devices(devlist):
    global settings

    devs = device.probe(devlist)

    for d in devs:
        try:
            d.init(settings)
            devices.append(d)
            devlist.remove(str(d))
        except:
            pass

    return devlist

def update():
    global failed
    global scanner
    global svc

    if scanner:
        svc['/Scan'] = scanner.running
        svc['/ScanProgress'] = 100 * scanner.done / scanner.total

        if not scanner.running:
            scan_complete()
            scanner = None

    for d in devices:
        update_device(d)

    init_devices(failed)

    return True

def percent(path, val):
    return '%d%%' % val

def main():
    global settings
    global svc

    parser = ArgumentParser(add_help=True)
    parser.add_argument('-d', '--debug', help='enable debug logging',
                        action='store_true')
    parser.add_argument('-f', '--force-scan', action='store_true')

    args = parser.parse_args()

    logging.basicConfig(format='%(levelname)-8s %(message)s',
                        level=(logging.DEBUG if args.debug else logging.INFO))

    gobject.threads_init()
    dbus.mainloop.glib.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    mainloop = gobject.MainLoop()

    svc = VeDbusService('com.victronenergy.modbusclient')

    svc.add_path('/Scan', False, writeable=True, onchangecallback=set_scan)
    svc.add_path('/ScanProgress', 0, gettextcallback=percent)

    log.info('waiting for localsettings')
    settings = SettingsDevice(svc.dbusconn, SETTINGS, None, timeout=10)

    saved_devices = settings['devices']

    if not saved_devices or init_devices(saved_devices.split(',')):
        start_scan()

    gobject.timeout_add(1000, update)
    mainloop.run()

if __name__ == '__main__':
    main()
