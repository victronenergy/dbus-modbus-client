import dbus
import logging
from pymodbus.register_read_message import ReadWriteMultipleRegistersResponse
import struct

from vedbus import VeDbusItemExport

log = logging.getLogger()

class VregLinkItem(VeDbusItemExport):
    def __init__(self, *args, getvreg=None, setvreg=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.getvreg = getvreg
        self.setvreg = setvreg

    @dbus.service.method('com.victronenergy.VregLink',
                         in_signature='q', out_signature='qay')
    def GetVreg(self, regid):
        return self.getvreg(int(regid))

    @dbus.service.method('com.victronenergy.VregLink',
                         in_signature='qay', out_signature='qay')
    def SetVreg(self, regid, data):
        return self.setvreg(int(regid), bytes(data))

class VregLink:
    def device_init_late(self):
        super().device_init_late()
        vregtype = lambda *args, **kwargs: VregLinkItem(*args, **kwargs,
            getvreg=self.vreglink_get, setvreg=self.vreglink_set)
        self.dbus.add_path('/Devices/0/VregLink', None, itemtype=vregtype)
        self.dbus.add_path('/Devices/0/DeviceInstance', self.devinst)
        self.dbus.add_path('/Devices/0/ProductId', self.productid)
        self.dbus.add_path('/Devices/0/ProductName', self.productname)
        self.dbus.add_path('/Devices/0/ServiceName', self.dbus.get_name())
        self.dbus.add_path('/Devices/0/CustomName', self.dbus['/CustomName'])
        self.dbus.add_path('/Devices/0/FirmwareVersion',
                           self.dbus['/FirmwareVersion'])

    def vreglink_get(self, regid):
        return self.vreglink_exec(regid)

    def vreglink_set(self, regid, data):
        return self.vreglink_exec(regid, data)

    def vreglink_exec(self, regid, data=None):
        iswrite = data is not None

        if iswrite:
            dlen = len(data)

            if dlen & 1:
                data += b'\0'

            data = struct.unpack('>%dH' % (len(data) / 2), data)
            data = [regid, dlen, *data]
        else:
            data = [regid]

        nread = 3 + self.vreglink_size

        r = self.modbus.readwrite_registers(read_address=self.vreglink_base,
                                            read_count=nread,
                                            write_address=self.vreglink_base,
                                            write_registers=data,
                                            unit=self.unit)

        if not isinstance(r, ReadWriteMultipleRegistersResponse):
            log.error('Modbus error accessing vreg %#04x: %s', regid, r)
            return 0x8100 if iswrite else 0x8000, []

        if r.registers[0] != regid:
            log.error('Invalid vreg response: %s', r.registers)
            return 0x8100 if iswrite else 0x8000, []

        stat = r.registers[1]
        size = r.registers[2]
        data = r.registers[3:]

        data = struct.pack('>%dH' % (len(data)), *data)

        if size > len(data):
            log.warning('Truncated data for vreg %04x: %s < %s',
                        regid, len(data), size)
            size = len(data)

        data = data[0:size]

        return stat, data
