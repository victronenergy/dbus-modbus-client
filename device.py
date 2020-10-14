from copy import copy
import dbus
from functools import partial
from pymodbus.client.sync import *
from pymodbus.register_read_message import ReadHoldingRegistersResponse
import logging
import os
import time
import traceback

from settingsdevice import SettingsDevice
from vedbus import VeDbusService

import __main__
from register import Reg
from utils import *

log = logging.getLogger()

class ModbusDevice(object):
    min_timeout = 0.1

    def __init__(self, modbus, unit, model):
        self.modbus = modbus.get()
        self.unit = unit
        self.model = model
        self.role = None
        self.info = {}
        self.dbus = None
        self.settings = None
        self.err_count = 0
        self.latency = modbus.timeout
        self.need_reinit = False

    def destroy(self):
        self.info = {}
        if self.dbus:
            self.dbus.__del__()
            self.dbus = None
        if self.settings:
            self.settings._settings = None
            self.settings = None
        self.modbus.put()

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return str(self) == str(other)
        if isinstance(other, (str, type(u''))):
            return str(self) == other
        return False

    def __hash__(self):
        return hash(str(self))

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
        if isinstance(self.modbus, (ModbusTcpClient, ModbusUdpClient)):
            return 'Modbus %s %s' % (self.method.upper(),
                                     self.modbus.socket.getpeername()[0])
        elif isinstance(self.modbus, ModbusSerialClient):
            return 'Modbus %s %s:%d' % (self.modbus.method.upper(),
                                        os.path.basename(self.modbus.port),
                                        self.unit)
        return 'Modbus'

    def read_register(self, reg):
        rr = self.modbus.read_holding_registers(reg.base, reg.count,
                                                unit=self.unit)

        if not isinstance(rr, ReadHoldingRegistersResponse):
            log.error('Error reading register %#04x: %s', reg.base, rr)
            raise Exception(rr)

        reg.decode(rr.registers)
        return reg.value

    def write_modbus(self, base, val):
        if len(val) == 1:
            self.modbus.write_register(base, val[0], unit=self.unit)
        else:
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

        rr = self.modbus.read_holding_registers(start, count, unit=self.unit)

        latency = time.time() - now

        if not isinstance(rr, ReadHoldingRegistersResponse):
            log.error('Error reading registers %#04x-%#04x: %s',
                      start, start + count - 1, rr)
            raise Exception(rr)

        for reg in regs:
            base = reg.base - start
            end = base + reg.count

            if now - reg.time > reg.max_age:
                if reg.decode(rr.registers[base:end]):
                    d[reg.name] = copy(reg) if reg.isvalid() else None
                reg.time = now

        return latency

    def read_info(self):
        if not self.info:
            self.read_info_regs(self.info)

    def init_device_settings(self, dbus):
        if self.settings:
            return

        self.settings_dbus = dbus

        path = '/Settings/Devices/' + self.get_ident()
        role = self.role or self.default_role
        def_inst = '%s:%s' % (self.default_role, self.default_instance)

        SETTINGS = {
            'instance':   [path + '/ClassAndVrmInstance', def_inst, 0, 0],
            'customname': [path + '/CustomName', '', 0, 0],
        }

        self.settings = SettingsDevice(dbus, SETTINGS, self.setting_changed)
        self.role, self.devinst = self.get_role_instance()

        if self.role == 'pvinverter':
            self.settings.addSettings({
                'position': [path + '/Position', 0, 0, 2]
            })

    def setting_changed(self, name, old, new):
        if name == 'customname':
            self.dbus['/CustomName'] = new
            return

        if name == 'instance':
            role, inst = self.get_role_instance()

            if role != self.role:
                self.role = role
                self.sched_reinit()
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
        self.destroy()
        self.init(self.settings_dbus)
        self.need_reinit = False

    def sched_reinit(self):
        self.need_reinit = True

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
        if not 0 <= val <= 2:
            return False

        self.settings['position'] = val
        return True

    def dbus_write_register(self, reg, path, val):
        try:
            val = get_super(Reg, reg)(val)

            if callable(reg.write):
                return reg.write(val)

            if isinstance(reg.write, list):
                if val not in reg.write:
                    return False

            if isinstance(reg.write, tuple):
                if not reg.write[0] <= val <= reg.write[1]:
                    return False

            self.write_register(reg, val)
            return True
        except:
            traceback.print_exc()

        return False

    def dbus_add_register(self, r):
        v = r if r.isvalid() else None
        if r.write:
            cb = partial(self.dbus_write_register, r)
            self.dbus.add_path(r.name, v, writeable=True, onchangecallback=cb)
        else:
            self.dbus.add_path(r.name, v)

    def pack_regs(self, regs):
        rr = []
        for r in regs:
            rr += r if isinstance(r, list) else [r]
        rr.sort(key=lambda r: r.base)

        overhead = 5 + 2                # request + response
        if self.method == 'tcp':
            overhead += 2 * (20 + 7)    # TCP + MBAP
        elif self.method == 'rtu':
            overhead += 2 * (1 + 2)     # address + crc

        regs = []
        rg = [rr.pop(0)]

        for r in rr:
            end = rg[-1].base + rg[-1].count
            nr = r.base + r.count - rg[0].base
            if nr > 125 or 2 * (r.base - end) > overhead:
                regs.append(rg)
                rg = []

            rg.append(r)

        if rg:
            regs.append(rg)

        return regs

    def init(self, dbus):
        self.device_init()
        self.read_info()
        self.init_device_settings(dbus)

        self.data_regs = self.pack_regs(self.data_regs)
        ident = self.get_ident()

        svcname = 'com.victronenergy.%s.%s' % (self.role, ident)
        self.dbus = VeDbusService(svcname, private_bus())

        self.dbus.add_path('/Mgmt/ProcessName', __main__.NAME)
        self.dbus.add_path('/Mgmt/ProcessVersion', __main__.VERSION)
        self.dbus.add_path('/Mgmt/Connection', self.connection())
        self.dbus.add_path('/DeviceInstance', self.devinst)
        self.dbus.add_path('/ProductId', self.productid)
        self.dbus.add_path('/ProductName', self.productname)
        self.dbus.add_path('/Model', self.model)
        self.dbus.add_path('/Connected', 1)
        self.dbus.add_path('/CustomName', self.get_customname(),
                           writeable=True,
                           onchangecallback=self.customname_changed)
        self.dbus.add_path('/Latency', None)

        if self.allowed_roles:
            self.dbus.add_path('/AllowedRoles', self.allowed_roles)
            self.dbus.add_path('/Role', self.role, writeable=True,
                               onchangecallback=self.role_changed)
        else:
            self.dbus.add_path('/Role', self.role)

        if self.role == 'pvinverter':
            self.dbus.add_path('/Position', self.settings['position'],
                               writeable=True,
                               onchangecallback=self.position_changed)

        for p in self.info:
            self.dbus_add_register(self.info[p])

        for r in self.data_regs:
            for rr in r:
                self.dbus_add_register(rr)

        self.latfilt = LatencyFilter(self.latency)
        self.device_init_late()

    def device_init(self):
        pass

    def device_init_late(self):
        pass

    def update(self):
        if self.need_reinit:
            self.reinit()

        latency = []

        for r in self.data_regs:
            t = self.read_data_regs(r, self.dbus)
            if t:
                latency.append(t)

        if latency:
            self.latency = self.latfilt.filter(latency)
            self.modbus.timeout = max(self.min_timeout, self.latency * 4)
            self.dbus['/Latency'] = round(self.latency * 1000)

class LatencyFilter(object):
    def __init__(self, val):
        self.length = 8
        self.pos = 0
        self.val = val
        self.values = [val] * self.length

    def filter(self, values):
        self.values[self.pos] = max(values)
        self.pos += 1
        self.pos &= self.length - 1

        val = max(self.values)

        if val > self.val:
            self.val = 0.25 * self.val + 0.75 * val
        else:
            self.val = 0.75 * self.val + 0.25 * val

        return self.val

class EnergyMeter(ModbusDevice):
    allowed_roles = ['grid', 'pvinverter', 'genset']
    default_role = 'grid'
    default_instance = 40

__all__ = [
    'EnergyMeter',
    'ModbusDevice',
]
