from copy import copy
import dbus
from pymodbus.client.sync import *
import logging

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

    def __del__(self):
        if self.dbus:
            self.dbus.__del__()

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return str(self) == str(other)
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
                                    self.modbus.port,
                                    self.modbus.baudrate,
                                    self.unit)
        return str(self.modbus)

    def connection(self):
        if isinstance(self.modbus, ModbusTcpClient):
            return 'Modbus TCP'
        elif isinstance(self.modbus, ModbusUdpClient):
            return 'Modbus UDP'
        elif isinstance(self.modbus, ModbusSerialClient):
            return 'Modbus %s' % self.modbus.method.upper()
        return 'Modbus'

    def read_info_regs(self, d):
        for reg in self.info_regs:
            rr = self.modbus.read_holding_registers(reg.base, reg.count,
                                                    unit=self.unit)
            reg.decode(rr.registers)
            d[reg.name] = reg

    def read_data_regs(self, d):
        regs = self.data_regs
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

    def init(self, settings):
        self.read_info_regs(self.info)

        role = self.get_role()
        ident = self.get_ident()
        devinstance = settings.getVrmDeviceInstance(ident, role,
                                                    self.default_instance)

        svcname = 'com.victronenergy.%s.%s' % (role, ident)
        self.dbus = VeDbusService(svcname, private_bus())

        self.dbus.add_path('/Mgmt/ProcessName', __main__.NAME)
        self.dbus.add_path('/Mgmt/ProcessVersion', __main__.VERSION)
        self.dbus.add_path('/Mgmt/Connection', self.connection())
        self.dbus.add_path('/DeviceInstance', devinstance)
        self.dbus.add_path('/ProductId', self.productid)
        self.dbus.add_path('/ProductName', self.productname)
        self.dbus.add_path('/Model', self.model)
        self.dbus.add_path('/Connected', 1)

        for p in self.info:
            self.dbus.add_path(p, self.info[p])

        for r in self.data_regs:
            self.dbus.add_path(r.name, None)

    def update(self):
        self.read_data_regs(self.dbus)

device_types = []

def make_modbus(m):
    method = m[0]

    if method == 'tcp':
        return ModbusTcpClient(m[1], int(m[2]))

    if method == 'udp':
        return ModbusUdpClient(m[1], int(m[2]))

    return ModbusSerialClient(method, port=m[1], baudrate=int(m[2]))

def probe(mlist, progress_cb=None, progress_interval=10):
    num_probed = 0
    found = []

    for m in mlist:
        if isinstance(m, (str, type(u''))):
            m = m.split(':')

        modbus = make_modbus(m)
        unit = int(m[-1])

        for t in device_types:
            d = t.probe(modbus, unit)
            if d:
                log.info('Found %s at %s' % (d.model, modbus))
                found.append(d)
                break

        num_probed += 1

        if progress_cb and num_probed == progress_interval:
            progress_cb(num_probed)
            num_probed = 0;

    if progress_cb and num_probed:
        progress_cb(num_probed)

    return found

def register(devtype):
    if devtype not in device_types:
        device_types.append(devtype)

__all__ = ['ModbusDevice', 'probe', 'register']
