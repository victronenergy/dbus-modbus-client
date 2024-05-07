from copy import copy
import dbus
from functools import partial
import logging
import os
import time
import traceback

from settingsdevice import SettingsDevice
from vedbus import VeDbusService, VeDbusItemImport, ServiceContext

import __main__
from register import Reg
from utils import *

class RegList(list):
    def __init__(self, access=None, regs=[]):
        super().__init__(regs)
        self.access = access

def modbus_overhead(method):
    overhead = 5 + 2                # request + response

    if method == 'tcp':
        overhead += 2 * (20 + 7)    # TCP + MBAP
    elif method == 'udp':
        overhead += 2 * (8 + 7)     # UDP + MBAP
    elif method == 'rtu':
        overhead += 2 * (1 + 2)     # address + crc

    return overhead

def contains_any(a, b, x):
    return any(a <= xx <= b for xx in x) if x else False

def pack_list(rr, access, hole_max, barrier):
    rr.sort(key=lambda r: r.base)

    regs = []
    rg = RegList(access, [rr.pop(0)])

    for r in rr:
        end = rg[-1].base + rg[-1].count
        nr = r.base + r.count - rg[0].base
        if nr > 125 or (r.base - end) > hole_max or \
           contains_any(end, r.base, barrier):
            regs.append(rg)
            rg = RegList()

        rg.append(r)

    if rg:
        regs.append(rg)

    return regs

class BaseDevice:
    min_timeout = 0.1
    refresh_time = None
    age_limit = 4
    age_limit_fast = 1
    fast_regs = ('/Ac/L1/Power', '/Ac/L2/Power', '/Ac/L3/Power', '/Ac/Power')
    allowed_roles = None
    default_access = 'holding'
    reg_hole_max = None
    reg_barrier = None

    def __init__(self):
        self.role = None
        self.info = {}
        self.dbus = None
        self.settings = None
        self._settings = None
        self.dbus_settings = {}
        self.info_regs = []
        self.data_regs = []

    def destroy(self):
        if self.dbus:
            self._dbus.__del__()
            self._dbus = None
            self.dbus = None
        if self.settings:
            self.settings._settings = None
            self.settings = None

    def pack_regs(self, regs):
        if self.reg_hole_max is not None:
            hole_max = self.reg_hole_max
        else:
            hole_max = (modbus_overhead(self.modbus.method) + 1) // 2

        regs = flatten(regs)

        ra = {}
        for r in regs:
            ra.setdefault(r.access or self.default_access, []).append(r)

        rr = []
        for a, r in ra.items():
            rr += pack_list(r, a, hole_max, self.reg_barrier)

        return rr

    def read_modbus(self, start, count, access):
        if access is None:
            access = self.default_access

        return self.modbus.read_registers(start, count, access, unit=self.unit)

    def read_register(self, reg):
        rr = self.read_modbus(reg.base, reg.count, reg.access)

        if rr.isError():
            self.log.error('Error reading register %#04x: %s', reg.base, rr)
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

        rr = self.read_modbus(start, count, regs.access)

        latency = time.time() - now

        if rr.isError():
            raise Exception('Error reading registers %#04x-%#04x: %s' %
                            (start, start + count - 1, rr))

        for reg in regs:
            base = reg.base - start
            end = base + reg.count

            if now - reg.time > reg.max_age:
                if reg.decode(rr.registers[base:end]) or not reg.time:
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

        def_inst = '%s:%s' % (self.default_role, self.default_instance)

        self._settings = {
            'instance': [self.settings_path + '/ClassAndVrmInstance', def_inst, 0, 0],
        }

        self.settings = SettingsDevice(dbus, self._settings, self.setting_changed)
        role, self.devinst = self.get_role_instance()

        if self.role:
            self.settings['instance'] = '%s:%s' % (self.role, self.devinst)
        else:
            self.role = role

    def setting_changed(self, name, old, new):
        if self.dbus and name in self.dbus_settings:
            self.dbus[self.dbus_settings[name]] = new

        if name == 'instance':
            role, inst = self.get_role_instance()

            if role != self.role:
                self.role = role
                self.sched_reinit()
                return True

            if self.dbus:
                self.dbus['/DeviceInstance'] = inst

            return True

        return False

    def add_settings(self, settings):
        for s in settings.values():
            if not s[0].startswith('/Settings/'):
                s[0] = self.settings_path + s[0]

        self._settings.update(settings)
        self.settings.addSettings(settings)

    def update_setting(self, setting, path, val):
        s = self._settings[setting]

        if type(s[1]) == type(s[2]): # valid range limits
            if not s[2] <= val <= s[3]:
                return False

        self.settings[setting] = val

        return True

    def add_dbus_setting(self, setting, path):
        self.dbus_settings[setting] = path
        cb = partial(self.update_setting, setting)
        self.dbus.add_path(path, self.settings[setting], writeable=True,
                           onchangecallback=cb)

    def get_role_instance(self, retry=True):
        try:
            val = self.settings['instance'].split(':')
            return val[0], int(val[1])
        except:
            if retry:
                self.log.info('Invalid role/instance, resetting')
                self.settings['instance'] = self._settings['instance'][1]
                return self.get_role_instance(False)
            raise

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
        v = copy(r) if r.isvalid() else None
        if r.write:
            cb = partial(self.dbus_write_register, r)
            self.dbus.add_path(r.name, v, writeable=True, onchangecallback=cb)
        else:
            self.dbus.add_path(r.name, v)

    def set_max_age(self, reg):
        if reg.name in self.fast_regs:
            reg.max_age = self.age_limit_fast
        else:
            reg.max_age = self.age_limit

    def init_dbus(self):
        ident = self.get_ident()

        svcname = 'com.victronenergy.%s.%s' % (self.role, ident)
        self._dbus = VeDbusService(svcname, private_bus())
        self.dbus = ServiceContext(self._dbus)

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

    def init_data_regs(self):
        self.data_regs = self.pack_regs(self.data_regs)

        for r in self.data_regs:
            for rr in r:
                if rr.max_age is None:
                    self.set_max_age(rr)
                if rr.name:
                    self.dbus_add_register(rr)

    def update_data_regs(self):
        latency = []

        for r in self.data_regs:
            t = self.read_data_regs(r, self.dbus)
            if t:
                latency.append(t)

        return latency

    def post_update(self):
        self.dbus.flush()

    def device_init(self):
        pass

    def device_init_late(self):
        pass

class ModbusDevice(BaseDevice):
    def __init__(self, spec, modbus, model):
        super().__init__()
        self.spec = spec
        self.modbus = modbus.get()
        self.unit = spec.unit
        self.model = model
        self.subdevices = []
        self.latency = modbus.timeout
        self.need_reinit = False
        self.log = logging.getLogger(str(self))
        self.log.addFilter(self)

    def filter(self, rec):
        rec.msg = '[%s] %s' % (self, rec.msg)
        return True

    def destroy(self):
        for s in self.subdevices:
            s.destroy()

        super().destroy()
        self.info.clear()
        self.modbus.put()

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.spec)

    def __str__(self):
        return str(self.spec)

    def connection(self):
        if self.modbus.method == 'tcp':
            return 'Modbus %s %s' % (self.modbus.method.upper(),
                                     self.modbus.socket.getpeername()[0])
        elif self.modbus.method == 'udp':
            return 'Modbus %s %s' % (self.modbus.method.upper(),
                                     self.modbus.host)
        elif self.modbus.method in ['rtu', 'ascii']:
            return 'Modbus %s %s:%d' % (self.modbus.method.upper(),
                                        os.path.basename(self.modbus.port),
                                        self.unit)
        return 'Modbus'

    def init_device_settings(self, dbus):
        if self.settings:
            return

        self.settings_path = '/Settings/Devices/' + self.get_ident()
        settings_root = VeDbusItemImport(dbus, 'com.victronenergy.settings',
                                         self.settings_path)
        def_enable = settings_root.exists

        super().init_device_settings(dbus)

        self.settings.addSettings({
            'enabled':  [self.settings_path + '/Enabled', def_enable, 0, 1],
        })

        if self.enabled:
            self.settings['enabled'] = 1
        else:
            self.enabled = self.settings['enabled']

    def setting_changed(self, name, old, new):
        if super().setting_changed(name, old, new):
            return True

        if name == 'enabled':
            if new != old:
                self.set_enabled(bool(new))
            return True

        return False

    def reinit(self):
        self.modbus.get()
        self.destroy()
        self.init(self.settings_dbus, self.enabled)
        self.need_reinit = False

    def sched_reinit(self):
        self.need_reinit = True

    def init(self, dbus, enable=True):
        self.enabled = enable
        self.modbus.timeout = self.timeout
        self.device_init()
        self.read_info()
        self.init_device_settings(dbus)
        self.need_reinit = False

        if not self.enabled:
            self.modbus.put()
            return

        self.init_dbus()
        self.init_data_regs()

        self.latfilt = LatencyFilter(self.latency)
        self.device_init_late()
        self.need_reinit = False

        self.dbus.flush()

        for s in self.subdevices:
            s.init()

    def update(self):
        if self.need_reinit:
            self.reinit()

        if not self.enabled:
            return

        self.modbus.timeout = self.timeout
        self.device_update()
        self.post_update()

    def device_update(self):
        latency = self.update_data_regs()

        for s in self.subdevices:
            s.device_update()
            s.post_update()

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

class SubDevice(BaseDevice):
    inherit_info = (
        '/Serial',
        '/FirmwareVersion',
        '/HardwareVersion',
    )

    def __init__(self, parent, subid):
        super().__init__()
        self.parent = parent
        self.subid = subid
        self.modbus = parent.modbus
        self.unit = parent.unit
        self.model = parent.model
        self.productid = parent.productid
        self.productname = parent.productname
        self.log = parent.log

    def connection(self):
        return self.parent.connection()

    def get_ident(self):
        return self.parent.get_ident() + '_%s' % self.subid

    def init(self):
        self.device_init()
        self.read_info()

        for i in self.inherit_info:
            if i in self.parent.info:
                self.info.setdefault(i, self.parent.info[i])

        self.init_device_settings(self.parent.settings_dbus)
        self.init_dbus()
        self.init_data_regs()
        self.device_init_late()
        self.dbus.flush()

    def sched_reinit(self):
        self.parent.sched_reinit()

    def device_update(self):
        self.update_data_regs()

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
    def device_init_late(self):
        super().device_init_late()
        self.add_settings({'customname': ['/CustomName', '', 0, 0]})
        self.add_dbus_setting('customname', '/CustomName')

class EnergyMeter(ModbusDevice):
    role_names = ['grid', 'pvinverter', 'genset', 'acload']
    allowed_roles = role_names
    default_role = 'grid'
    default_instance = 40
    nr_phases = None
    position = None

    def device_init_late(self):
        super().device_init_late()

        if self.nr_phases is not None:
            self.dbus.add_path('/NrOfPhases', self.nr_phases)

        if self.role == 'pvinverter' and self.position is None:
            self.add_settings({'position': ['/Position', 0, 0, 2]})
            self.add_dbus_setting('position', '/Position')

class Tank:
    default_role = 'tank'
    default_instance = 20

    def device_init_late(self):
        super().device_init_late()

        rvmin = self.raw_value_min
        rvmax = self.raw_value_max

        self.add_settings({
            'capacity':       ['/Capacity', 0.2, 0, 1000],
            'fluidtype':      ['/FluidType', 0, 0, 11],
            'rawvalempty':    ['/RawValueEmpty', rvmin, rvmin, rvmax],
            'rawvalfull':     ['/RawValueFull', rvmax, rvmin, rvmax],
        })

        self.add_dbus_setting('capacity', '/Capacity')
        self.add_dbus_setting('fluidtype', '/FluidType')
        self.add_dbus_setting('rawvalempty', '/RawValueEmpty')
        self.add_dbus_setting('rawvalfull', '/RawValueFull')

        self.dbus.add_path('/RawUnit', self.raw_unit)
        self.dbus.add_path('/Level', None)
        self.dbus.add_path('/Remaining', None)

    def device_update(self):
        super().device_update()

        rvempty = self.settings['rawvalempty']
        rvfull = self.settings['rawvalfull']

        rvlo = min(rvempty, rvfull)
        rvhi = max(rvempty, rvfull)

        rval = float(self.dbus['/RawValue'])
        rval = min(max(rval, rvlo), rvhi)

        level = (rval - rvempty) / (rvfull - rvempty)
        remain = level * self.settings['capacity']

        self.dbus['/Level'] = 100 * level
        self.dbus['/Remaining'] = remain

__all__ = [
    'CustomName',
    'EnergyMeter',
    'ModbusDevice',
    'SubDevice',
]
