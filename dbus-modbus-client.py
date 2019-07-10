#! /usr/bin/python -u

from argparse import ArgumentParser
from copy import copy
import dbus
import dbus.mainloop.glib
import gobject
import ipaddress
import os
from pymodbus.client.sync import *
import pymodbus.exceptions
import re
from settingsdevice import SettingsDevice
import struct
import threading
import traceback
from vedbus import VeDbusService

import logging
log = logging.getLogger()

NAME = os.path.basename(__file__)
VERSION = '0.1'

MODBUS_PORT = 502
MODBUS_UNIT = 1

SETTINGS = {
    'meters': ['/Settings/ModbusClient/Meters', '', 0, 0],
}

class Reg(object):
    def __init__(self, base, count, name):
        self.base = base
        self.count = count
        self.name = name
        self.value = None

    def __eq__(self, other):
        if isinstance(other, Reg):
            return self.value == other.value
        return False

    def __float__(self):
        return float(self.value)

    def __int__(self):
        return int(self.value)

    def __str__(self):
        return str(self.value)

    def isvalid(self):
        return self.value is not None

    def update(self, newval):
        old = self.value
        self.value = newval
        return newval != old

class Reg_num(Reg, float):
    def __new__(cls, *args):
        return float.__new__(cls)

    def __init__(self, base, count, name, scale=1, fmt=None):
        Reg.__init__(self, base, count, name)
        self.scale = float(scale)
        self.fmt = fmt

    def __str__(self):
        if self.fmt:
            return self.fmt % self.value
        return str(self.value)

    def set_raw_value(self, val):
        return self.update(val / self.scale)

class Reg_uint16(Reg_num):
    def decode(self, values):
        if values[0] == 0x7ffff:
            return self.update(None)

        return self.set_raw_value(values[0])

class Reg_int32(Reg_num):
    def decode(self, values):
        if values[1] == 0x7ffff:
            return self.update(None)

        v = struct.unpack('<i', struct.pack('<2H', *values))[0]
        return self.set_raw_value(v)

class Reg_text(Reg, str):
    def __new__(cls, *args):
        return str.__new__(cls)

    def decode(self, values):
        newval = struct.pack('>%dH' % len(values), *values).rstrip('\0')
        return self.update(newval)

class Reg_map(Reg):
    def __init__(self, base, count, name, tab):
        Reg.__init__(self, base, count, name)
        self.tab = tab

    def decode(self, values):
        if values[0] in self.tab:
            v = self.tab[values[0]]
        else:
            v = None
        return self.update(v)

class Reg_mapstr(Reg_map, Reg_text):
    pass

def private_bus():
    if 'DBUS_SESSION_BUS_ADDRESS' in os.environ:
        return dbus.SessionBus(private=True)
    return dbus.SystemBus(private=True)

class ModbusMeter(object):
    def __init__(self, modbus, unit):
        self.modbus = modbus
        self.unit = unit
        self.info = {}
        self.dbus = None

    def __del__(self):
        if self.dbus:
            self.dbus.__del__()

    def __str__(self):
        if isinstance(self.modbus, ModbusTcpClient):
            return 'tcp:%s:%d:%d' % (self.modbus.host,
                                     self.modbus.port,
                                     self.unit)
        elif isinstance(self.modbus, ModbusUdpClient):
            return 'udp:%s:%d:%d' % (self.modbus.host,
                                     self.modbus.port,
                                     self.unit)
        elif isinstance(self.modbus, ModbusSerialClient):
            return '%s:%s:%d:%d' % (self.modbus.method,
                                    self.modbus.port,
                                    self.modbus.baudrate,
                                    self.unit)
        return str(self.modbus)

    def read_single_regs(self, regs, d):
        for reg in regs:
            rr = self.modbus.read_holding_registers(reg.base, reg.count,
                                                    unit=self.unit)
            reg.decode(rr.registers)
            d[reg.name] = reg

    def read_regs(self, regs, d):
        start = regs[0].base
        count = regs[-1].base + regs[-1].count - start

        rr = self.modbus.read_holding_registers(start, count, unit=self.unit)

        for reg in regs:
            base = reg.base - start
            end = base + reg.count
            if reg.decode(rr.registers[base:end]):
                d[reg.name] = copy(reg) if reg.isvalid() else None

    def get_role(self):
        # TODO: get from settings
        return self.default_role

    def init(self):
        global settings

        self.read_single_regs(self.info_regs, self.info)

        if '/Serial' not in self.info:
            return False

        role = self.get_role()
        ident = self.get_ident()
        devinstance = settings.getVrmDeviceInstance(ident, role,
                                                    self.default_instance)

        svcname = 'com.victronenergy.%s.%s' % (role, ident)
        self.dbus = VeDbusService(svcname, private_bus())

        self.dbus.add_path('/Mgmt/Processname', NAME)
        self.dbus.add_path('/Mgmt/ProcessVersion', VERSION)
        self.dbus.add_path('/Mgmt/Connection', 'Modbus TCP')
        self.dbus.add_path('/DeviceInstance', devinstance)
        self.dbus.add_path('/ProductId', self.productid)
        self.dbus.add_path('/ProductName', self.productname)
        self.dbus.add_path('/Connected', 1)

        for p in self.info:
            self.dbus.add_path(p, self.info[p])

        for r in self.data_regs:
            self.dbus.add_path(r.name, None)

        return True

    def update(self):
        self.read_regs(self.data_regs, self.dbus)

class Reg_cgver(Reg, int):
    def __new__(cls, *args):
        return int.__new__(cls)

    def __int__(self):
        v = self.value
        return v[0] << 16 | v[1] << 8 | v[2]

    def __str__(self):
        return '%d.%d.%d' % self.value

    def decode(self, values):
        v = values[0]
        return self.update((v >> 12, v >> 8 & 0xf, v & 0xff))

CG_EM24_MODELS = {
    0x670: 'EM24DINAV23XE1X',
    0x671: 'EM24DINAV23XE1PFA',
    0x672: 'EM24DINAV23XE1PFB',
    0x673: 'EM24DINAV53XE1X',
    0x674: 'EM24DINAV53XE1PFA',
    0x675: 'EM24DINAV53XE1PFB',
}

class CG_EM24_Meter(ModbusMeter):
    productid = 0xb002
    productname = 'Carlo Gavazzi EM24 Energy Meter'
    default_role = 'grid'
    default_instance = 40

    def __init__(self, *args):
        ModbusMeter.__init__(self, *args)

        self.info_regs = [
            Reg_mapstr(0x000b, 1, '/Model', CG_EM24_MODELS),
            Reg_cgver( 0x0302, 1, '/HardwareVersion'),
            Reg_cgver( 0x0304, 1, '/FirmwareVersion'),
            Reg_text(  0x5000, 7, '/Serial'),
        ]

        self.data_regs = [
            Reg_int32( 0x0000, 2, '/Ac/L1/Voltage',        10,   '%.1f V'),
            Reg_int32( 0x0002, 2, '/Ac/L2/Voltage',        10,   '%.1f V'),
            Reg_int32( 0x0004, 2, '/Ac/L3/Voltage',        10,   '%.1f V'),
            Reg_int32( 0x000c, 2, '/Ac/L1/Current',        1000, '%.1f A'),
            Reg_int32( 0x000e, 2, '/Ac/L2/Current',        1000, '%.1f A'),
            Reg_int32( 0x0010, 2, '/Ac/L3/Current',        1000, '%.1f A'),
            Reg_int32( 0x0012, 2, '/Ac/L1/Power',          10,   '%.1f W'),
            Reg_int32( 0x0014, 2, '/Ac/L2/Power',          10,   '%.1f W'),
            Reg_int32( 0x0016, 2, '/Ac/L3/Power',          10,   '%.1f W'),
            Reg_int32( 0x0028, 2, '/Ac/Power',             10,   '%.1f W'),
            Reg_uint16(0x0033, 1, '/Ac/Frequency',         10,   '%.1f Hz'),
            Reg_int32( 0x0034, 2, '/Ac/Energy/Forward',    10,   '%.1f kWh'),
            Reg_int32( 0x0040, 2, '/Ac/L1/Energy/Forward', 10,   '%.1f kWh'),
            Reg_int32( 0x0042, 2, '/Ac/L2/Energy/Forward', 10,   '%.1f kWh'),
            Reg_int32( 0x0044, 2, '/Ac/L3/Energy/Forward', 10,   '%.1f kWh'),
            Reg_int32( 0x004e, 2, '/Ac/Energy/Reverse',    10,   '%.1f kWh'),
        ]

    def get_ident(self):
        return 'cg_%s' % self.info['/Serial']

cg_models = {
    1648: {
        'model':    'EM24DINAV23XE1X',
        'handler':  CG_EM24_Meter
    },
    1649: {
        'model':    'EM24DINAV23XE1PFA',
        'handler':  CG_EM24_Meter,
    },
    1650: {
        'model':    'EM24DINAV23XE1PFB',
        'handler':  CG_EM24_Meter,
    },
    1651: {
        'model':    'EM24DINAV53XE1X',
        'handler':  CG_EM24_Meter,
    },
    1652: {
        'model':    'EM24DINAV53XE1PFA',
        'handler':  CG_EM24_Meter,
    },
    1653: {
        'model':    'EM24DINAV53XE1PFB',
        'handler':  CG_EM24_Meter,
    },
}

class timeout(object):
    def __init__(self, obj, timeout):
        self.obj = obj
        self.timeout = timeout

    def __enter__(self):
        self.orig_timeout = self.obj.timeout
        self.obj.timeout = self.timeout

    def __exit__(self, exc_type, exc_value, traceback):
        self.obj.timeout = self.orig_timeout

def probe_cg(modbus, unit):
    try:
        logging.disable(logging.ERROR)
        with timeout(modbus, 0.1):
            rr = modbus.read_holding_registers(0xb, 1, unit=unit)
        return cg_models[rr.registers[0]]
    except:
        return None
    finally:
        logging.disable(logging.NOTSET)

probe_funcs = [
    probe_cg,
]

def make_modbus(m):
    method = m[0]

    if method == 'tcp':
        return ModbusTcpClient(m[1], int(m[2]))

    if method == 'udp':
        return ModbusUdpClient(m[1], int(m[2]))

    return ModbusSerialClient(method, port=m[1], baudrate=int(m[2]))

def probe_meters(mlist, progress_cb=None, progress_interval=10):
    num_probed = 0
    found = []

    for m in mlist:
        modbus = make_modbus(m)
        unit = int(m[-1])

        for p in probe_funcs:
            model = p(modbus, unit)
            if model:
                log.info('Found %s at %s' % (model['model'], modbus))
                found.append(model['handler'](modbus, unit))
                break

        num_probed += 1

        if progress_cb and num_probed == progress_interval:
            progress_cb(num_probed)
            num_probed = 0;

    if progress_cb:
        progress_cb(num_probed)

    return found

if_blacklist = [
    'ap0',
]

def get_nets():
    nets = []
    num_addrs = 0

    try:
        with os.popen('ip -br -4 addr show scope global up') as ip:
            for line in ip:
                v = line.split()
                if v[0] in if_blacklist:
                    continue

                net = ipaddress.IPv4Network(u'' + v[2], strict=False)
                nets.append(net)
                num_addrs += net.num_addresses - 2
    except:
        log.warn('Unable to get network addresses')
        pass

    return nets, num_addrs

class ScanAborted(Exception):
    pass

class Progress(object):
    def __init__(self, dbus, num):
        self.dbus = dbus
        self.num = num
        self.scanned = 0

    def progress(self, n):
        global scanning

        self.scanned += n
        self.dbus['/ScanProgress'] = 100 * self.scanned / self.num

        if not scanning:
            raise ScanAborted()

def scan_net():
    global meters
    global scan_lock
    global settings
    global svc

    with scan_lock:
        for m in meters:
            m.__del__()
        meters = []

    nets, num_addrs = get_nets()
    num_probed = 0
    found = []
    pr = Progress(svc, num_addrs)

    for net in nets:
        log.info('scanning %s' % net)
        hosts = net.hosts()
        mlist = [['tcp', str(h), MODBUS_PORT, MODBUS_UNIT] for h in hosts]
        found += probe_meters(mlist, pr.progress)

    log.info('Scan complete, %d device(s) found' % len(found))

    for m in found:
        m.init()

    meters = found
    settings['meters'] = ','.join([str(m) for m in meters])

scanning = False
scan_lock = threading.Lock()

def run_scan():
    global scanning
    global svc

    try:
        scan_net()
    except ScanAborted:
        log.info('Scan aborted')
    except:
        log.warn('Exception during network scan')
        traceback.print_exc()
        pass

    scanning = False
    svc['/Scan'] = False
    svc['/ScanProgress'] = None

def start_scan():
    global scanning
    global scan_lock

    with scan_lock:
        if scanning:
            return

        log.info('Starting background scan')

        scanning = True
        threading.Thread(target=run_scan).start()

def stop_scan():
    global scanning
    global scan_lock

    with scan_lock:
        scanning = False

def set_scan(path, val):
    if val:
        start_scan()
    else:
        stop_scan()

    return True

meters = []

def update_meters():
    global scan_lock

    try:
        with scan_lock:
            for m in meters:
                m.update()
    except:
        traceback.print_exc()
        os._exit(1)

    return True

def main():
    global meters
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
    svc.add_path('/ScanProgress', None)

    log.info('waiting for localsettings')
    settings = SettingsDevice(svc.dbusconn, SETTINGS, None, timeout=10)

    known_meters = None

    if not args.force_scan:
        known_meters = settings['meters'].split(',')

    if known_meters:
        try:
            meters = probe_meters([m.split(':') for m in known_meters])
            if len(meters) != len(known_meters):
                meters = []

            for m in meters:
                m.init()
        except:
            meters = []

    if not meters:
        start_scan()

    gobject.timeout_add(1000, update_meters)
    mainloop.run()

if __name__ == '__main__':
    main()
