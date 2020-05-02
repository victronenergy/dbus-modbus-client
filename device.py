from copy import copy
import dbus
from functools import partial
from pymodbus.client.sync import *
from pymodbus.pdu import ExceptionResponse
import logging
import os
import time
import threading

from settingsdevice import SettingsDevice
from vedbus import VeDbusService

import __main__
from utils import *

log = logging.getLogger()

class ModbusDevice(object):
    def __init__(self, modbus, unit, model):
        self.modbus = modbus
        self.unit = unit
        self.model = model
        self.info = {}
        self.dbus = None
        self.settings = None
        self.err_count = 0

    def __del__(self):
        if self.dbus:
            self.dbus.__del__()

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return str(self) == str(other)
        if isinstance(other, (str, type(u''))):
            return str(self) == other
        return False

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
                                    os.path.basename(self.modbus.port),
                                    self.modbus.baudrate,
                                    self.unit)
        return str(self.modbus)

    def connection(self):
        if isinstance(self.modbus, ModbusTcpClient):
            return 'Modbus TCP %s' % self.modbus.host
        elif isinstance(self.modbus, ModbusUdpClient):
            return 'Modbus UDP % ' % self.modbus.host
        elif isinstance(self.modbus, ModbusSerialClient):
            return 'Modbus %s %s:%d' % (self.modbus.method.upper(),
                                        os.path.basename(self.modbus.port),
                                        self.unit)
        return 'Modbus'

    def read_register(self, reg):
        with self.modbus.lock:
            rr = self.modbus.read_holding_registers(reg.base, reg.count,
                                                    unit=self.unit)
        reg.decode(rr.registers)
        return reg.value

    def write_modbus(self, base, val):
        with self.modbus.lock:
            self.modbus.write_registers(base, val, unit=self.unit)

    def write_register(self, reg, val):
        reg.value = val
        self.write_modbus(reg.base, reg.encode())

    def read_info_regs(self, d):
        for reg in self.info_regs:
            self.read_register(reg)
            d[reg.name] = reg

    def read_data_regs(self, regs, d):
        now = time.time()

        if all(now - r.time < r.max_age for r in regs):
            return

        start = regs[0].base
        count = regs[-1].base + regs[-1].count - start

        with self.modbus.lock:
            rr = self.modbus.read_holding_registers(start, count,
                                                    unit=self.unit)

        if isinstance(rr, ExceptionResponse):
            log.error('Error reading registers %#04x-%#04x: %s',
                      regs[0].base, regs[-1].base, rr)
            raise Exception(rr)

        for reg in regs:
            base = reg.base - start
            end = base + reg.count

            if now - reg.time > reg.max_age:
                if reg.decode(rr.registers[base:end]):
                    d[reg.name] = copy(reg) if reg.isvalid() else None
                reg.time = now

    def read_info(self):
        if not self.info:
            self.read_info_regs(self.info)

    def init_device_settings(self, dbus):
        if self.settings:
            return

        path = '/Settings/Devices/' + self.get_ident()
        def_inst = '%s:%s' % (self.default_role, self.default_instance)

        SETTINGS = {
            'instance':   [path + '/ClassAndVrmInstance', def_inst, 0, 0],
            'customname': [path + '/CustomName', '', 0, 0],
            'position':   [path + '/Position', 0, 0, 2],
        }

        self.settings = SettingsDevice(dbus, SETTINGS, self.setting_changed)

    def setting_changed(self, name, old, new):
        if name == 'customname':
            self.dbus['/CustomName'] = new
            return

        if name == 'instance':
            role, inst = self.get_role_instance()

            if role != self.role:
                self.reinit()
                return

            self.dbus['/DeviceInstance'] = inst
            return

        if name == 'position':
            if self.role == 'pvinverter':
                self.dbus['/Position'] = new
            return

    def get_role_instance(self):
        val = self.settings['instance'].split(':')
        return val[0], int(val[1])

    def reinit(self):
        self.dbus.__del__()
        self.info = {}
        self.init(None)

    def get_customname(self):
        return self.settings['customname']

    def set_customname(self, val):
        self.settings['customname'] = val

    def customname_changed(self, path, val):
        self.set_customname(val)
        return True

    def role_changed(self, path, val):
        if val not in self.allowed_roles:
            return False

        old, inst = self.get_role_instance()
        self.settings['instance'] = '%s:%s' % (val, inst)
        return True

    def position_changed(self, path, val):
        if val not in range(3):
            return False

        self.settings['position'] = val
        return True

    def dbus_write_register(self, reg, path, val):
        self.write_register(reg, val)
        return True

    def init(self, dbus):
        self.device_init()
        self.read_info()
        self.init_device_settings(dbus)

        self.role, devinstance = self.get_role_instance()
        ident = self.get_ident()

        svcname = 'com.victronenergy.%s.%s' % (self.role, ident)
        self.dbus = VeDbusService(svcname, private_bus())

        self.dbus.add_path('/Mgmt/ProcessName', __main__.NAME)
        self.dbus.add_path('/Mgmt/ProcessVersion', __main__.VERSION)
        self.dbus.add_path('/Mgmt/Connection', self.connection())
        self.dbus.add_path('/DeviceInstance', devinstance)
        self.dbus.add_path('/ProductId', self.productid)
        self.dbus.add_path('/ProductName', self.productname)
        self.dbus.add_path('/Model', self.model)
        self.dbus.add_path('/Connected', 1)
        self.dbus.add_path('/AllowedRoles', self.allowed_roles)

        self.dbus.add_path('/CustomName', self.get_customname(),
                           writeable=True,
                           onchangecallback=self.customname_changed)
        self.dbus.add_path('/Role', self.role, writeable=True,
                           onchangecallback=self.role_changed);

        if self.role == 'pvinverter':
            self.dbus.add_path('/Position', self.settings['position'],
                               writeable=True,
                               onchangecallback=self.position_changed)

        for p in self.info:
            r = self.info[p]
            if r.writable:
                cb = partial(self.dbus_write_register, r)
                self.dbus.add_path(p, r, writeable=True, onchangecallback=cb)
            else:
                self.dbus.add_path(p, r)

        for r in self.data_regs:
            for rr in r if isinstance(r, list) else [r]:
                self.dbus.add_path(rr.name, None)

        self.device_init_late()

    def device_init(self):
        pass

    def device_init_late(self):
        pass

    def update(self):
        for r in self.data_regs:
            self.read_data_regs(r if isinstance(r, list) else [r], self.dbus)

class EnergyMeter(ModbusDevice):
    allowed_roles = ['grid', 'pvinverter', 'genset']
    default_role = 'grid'
    default_instance = 40

class ModelRegister(object):
    def __init__(self, reg, models, timeout=0.1):
        self.reg = reg
        self.models = models
        self.timeout = timeout

    def probe(self, modbus, unit):
        with modbus.lock:
            with timeout(modbus, self.timeout):
                rr = modbus.read_holding_registers(self.reg, 1, unit=unit)
        m = self.models[rr.registers[0]]
        return m['handler'](modbus, unit, m['model'])

device_types = []
serial_ports = {}

def lockable(obj):
    obj.lock = threading.Lock()
    return obj

def make_modbus(m):
    method = m[0]

    if method == 'tcp':
        return lockable(ModbusTcpClient(m[1], int(m[2])))

    if method == 'udp':
        return lockable(ModbusUdpClient(m[1], int(m[2])))

    tty = m[1]

    if tty in serial_ports:
        return serial_ports[tty]

    dev = '/dev/%s' % tty
    client = lockable(ModbusSerialClient(method, port=dev, baudrate=int(m[2])))
    serial_ports[tty] = client

    return client

def probe_one(devtype, modbus, unit):
    try:
        return devtype.probe(modbus, unit)
    except KeyboardInterrupt:
        os._exit(1)
    except:
        pass

def probe(mlist, progress_cb=None, progress_interval=10):
    num_probed = 0
    found = []

    for m in mlist:
        if isinstance(m, (str, type(u''))):
            m = m.split(':')

        if len(m) < 4:
            continue

        modbus = make_modbus(m)
        unit = int(m[-1])

        for t in device_types:
            d = probe_one(t, modbus, unit)
            if d:
                log.info('Found %s at %s', d.model, d)
                found.append(d)
                break

        num_probed += 1

        if progress_cb and num_probed == progress_interval:
            progress_cb(num_probed)
            num_probed = 0;

    if progress_cb and num_probed:
        progress_cb(num_probed)

    return found

def add_handler(devtype):
    if devtype not in device_types:
        device_types.append(devtype)

__all__ = [
    'EnergyMeter',
    'ModbusDevice',
    'ModelRegister',
    'probe',
    'add_handler'
]
