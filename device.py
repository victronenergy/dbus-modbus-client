from copy import copy
import dbus
from functools import partial
import logging
import os
import time
import traceback

from settingsdevice import SettingsDevice
from vedbus import VeDbusService, VeDbusItemImport

import __main__
from register import Reg
from utils import *

log = logging.getLogger()

class ModbusDevice:
    min_timeout = 0.1
    refresh_time = None
    age_limit = 4
    age_limit_fast = 1
    fast_regs = ('/Ac/L1/Power', '/Ac/L2/Power', '/Ac/L3/Power', '/Ac/Power')

    def __init__(self, spec, modbus, model):
        self.spec = spec
        self.modbus = modbus.get()
        self.method = modbus.method
        self.unit = spec.unit
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
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.spec)

    def __str__(self):
        return str(self.spec)

    def connection(self):
        if self.method == 'tcp':
            return 'Modbus %s %s' % (self.method.upper(),
                                     self.modbus.socket.getpeername()[0])
        elif self.method == 'udp':
            return 'Modbus %s %s' % (self.method.upper(),
                                     self.modbus.host)
        elif self.method in ['rtu', 'ascii']:
            return 'Modbus %s %s:%d' % (self.method.upper(),
                                        os.path.basename(self.modbus.port),
                                        self.unit)
        return 'Modbus'

    def read_register(self, reg):
        rr = self.modbus.read_holding_registers(reg.base, reg.count,
                                                unit=self.unit)

        if rr.isError():
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
        register_type = regs[0].base_register_type

        rr = None
        if(register_type == 3):
            rr = self.modbus.read_input_registers(start, count, unit=self.unit)
        else:
            rr = self.modbus.read_holding_registers(start, count, unit=self.unit)

        latency = time.time() - now

        if rr.isError():
            log.error('Error reading registers %#04x-%#04x: %s',
                      start, start + count - 1, rr)
            raise Exception(rr)

        for reg in regs:
            base = reg.base - start
            end = base + reg.count

            if now - reg.time > reg.max_age:
                if reg.decode(rr.registers[base:end]):
                    if reg.name:
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
        self.settings_path = '/Settings/Devices/' + self.get_ident()

        settings_root = VeDbusItemImport(dbus, 'com.victronenergy.settings',
                                         self.settings_path)

        def_enable = settings_root.exists
        def_inst = '%s:%s' % (self.default_role, self.default_instance)

        SETTINGS = {
            'enabled':  [self.settings_path + '/Enabled', def_enable, 0, 1],
            'instance': [self.settings_path + '/ClassAndVrmInstance', def_inst, 0, 0],
        }

        self.settings = SettingsDevice(dbus, SETTINGS, self.setting_changed)
        role, self.devinst = self.get_role_instance()

        if self.role:
            self.settings['instance'] = '%s:%s' % (self.role, self.devinst)
        else:
            self.role = role

        if self.enabled:
            self.settings['enabled'] = 1
        else:
            self.enabled = self.settings['enabled']

    def setting_changed(self, name, old, new):
        if name == 'instance':
            role, inst = self.get_role_instance()

            if role != self.role:
                self.role = role
                self.sched_reinit()
                return

            if self.dbus:
                self.dbus['/DeviceInstance'] = inst

            return

        if name == 'enabled':
            if new != old:
                self.set_enabled(bool(new))
            return

    def get_role_instance(self):
        val = self.settings['instance'].split(':')
        return val[0], int(val[1])

    def reinit(self):
        self.modbus.get()
        self.destroy()
        self.init(self.settings_dbus, self.enabled)
        self.need_reinit = False

    def sched_reinit(self):
        self.need_reinit = True

    def role_changed(self, path, val):
        if val not in self.allowed_roles:
            return False

        old, inst = self.get_role_instance()
        self.settings['instance'] = '%s:%s' % (val, inst)
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
        if r.name in self.dbus:
            del self.dbus[r.name]
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
        rr.sort(key=lambda r: 10000*r.base_register_type + r.base)

        overhead = 5 + 2                # request + response
        if self.method == 'tcp':
            overhead += 2 * (20 + 7)    # TCP + MBAP
        elif self.method == 'udp':
            overhead += 2 * (8 + 7)     # UDP + MBAP
        elif self.method == 'rtu':
            overhead += 2 * (1 + 2)     # address + crc

        regs = []
        r = rr.pop(0)
        brt = r.base_register_type
        rg = [r]

        for r in rr:
            end = rg[-1].base + rg[-1].count
            nr = r.base + r.count - rg[0].base
            if nr > 125 or 2 * (r.base - end) > overhead or r.base_register_type != brt:
                regs.append(rg)
                rg = []

            rg.append(r)

        if rg:
            regs.append(rg)

        return regs

    def set_max_age(self, reg):
        if reg.name in self.fast_regs:
            reg.max_age = self.age_limit_fast
        else:
            reg.max_age = self.age_limit

    def init(self, dbus, enable=True):
        self.enabled = enable
        self.device_init()
        self.read_info()
        self.init_device_settings(dbus)
        self.need_reinit = False

        if not self.enabled:
            self.modbus.put()
            return

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

        if self.allowed_roles:
            self.dbus.add_path('/AllowedRoles', self.allowed_roles)
            self.dbus.add_path('/Role', self.role, writeable=True,
                               onchangecallback=self.role_changed)
        else:
            self.dbus.add_path('/Role', self.role)

        if self.refresh_time is not None:
            self.dbus.add_path('/RefreshTime', self.refresh_time)

        for p in self.info:
            self.dbus_add_register(self.info[p])

        for r in self.data_regs:
            for rr in r:
                if rr.max_age is None:
                    self.set_max_age(rr)
                if rr.name:
                    self.dbus_add_register(rr)

        self.latfilt = LatencyFilter(self.latency)
        self.device_init_late()
        self.need_reinit = False

    def device_init(self):
        pass

    def device_init_late(self):
        pass

    def update(self):
        if self.need_reinit:
            self.reinit()

        if not self.enabled:
            return

        self.modbus.timeout = self.timeout
        latency = []

        with self.dbus as d:
            for r in self.data_regs:
                t = self.read_data_regs(r, d)
                if t:
                    latency.append(t)

        if latency:
            self.latency = self.latfilt.filter(latency)
            self.timeout = max(self.min_timeout, self.latency * 4)

    def set_enabled(self, enabled):
        if enabled == self.enabled:
            return

        self.enabled = enabled
        self.settings['enabled'] = enabled
        if enabled:
            self.modbus.get()
        self.sched_reinit()

class LatencyFilter:
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

class CustomName:
    def customname_setting_changed(self, service, path, value):
        self.dbus['/CustomName'] = value['Value']

    def init_device_settings(self, dbus):
        super().init_device_settings(dbus)
        self.cn_item = self.settings.addSetting(
            self.settings_path + '/CustomName', '', 0, 0,
            callback=self.customname_setting_changed)

    def device_init_late(self):
        super().device_init_late()
        self.dbus.add_path('/CustomName', self.cn_item.get_value(),
                           writeable=True,
                           onchangecallback=self.customname_changed)

    def customname_changed(self, path, val):
        self.cn_item.set_value(val)
        return True

class EnergyMeter(ModbusDevice):
    role_names = ['grid', 'pvinverter', 'genset', 'acload']
    allowed_roles = role_names
    default_role = 'grid'
    default_instance = 40
    nr_phases = None

    def position_setting_changed(self, service, path, value):
        self.dbus['/Position'] = value['Value']

    def init_device_settings(self, dbus):
        super().init_device_settings(dbus)

        self.pos_item = None
        if self.role == 'pvinverter':
            self.pos_item = self.settings.addSetting(
                self.settings_path + '/Position', 0, 0, 2,
                callback=self.position_setting_changed)

    def device_init_late(self):
        super().device_init_late()

        if self.nr_phases is not None:
            self.dbus.add_path('/NrOfPhases', self.nr_phases)

        if self.pos_item is not None:
            self.dbus.add_path('/Position', self.pos_item.get_value(),
                               writeable=True,
                               onchangecallback=self.position_changed)

    def position_changed(self, path, val):
        if not 0 <= val <= 2:
            return False
        self.pos_item.set_value(val)
        return True

__all__ = [
    'CustomName',
    'EnergyMeter',
    'ModbusDevice',
]
