from enum import IntEnum
import struct

import device
import mdns
import probe
from register import *

class EVC_MODE(IntEnum):
    MANUAL          = 0
    AUTO            = 1

class EVC_STATUS(IntEnum):
    DISCONNECTED    = 0
    CONNECTED       = 1
    CHARGING        = 2
    CHARGED         = 3
    WAIT_SUN        = 4
    WAIT_RFID       = 5
    WAIT_START      = 6
    LOW_SOC         = 7
    GND_ERROR       = 8
    WELD_CON        = 9

class Reg_ver(Reg, int):
    def __init__(self, base, name):
        Reg.__init__(self, base, 2, name)

    def __int__(self):
        v = self.value
        return v[0] << 24 | v[1] << 16 | v[2] << 8 | v[3]

    def __str__(self):
        return '%d.%d.%d.%d' % self.value

    def decode(self, values):
        return self.update(struct.unpack('4B', struct.pack('>2H', *values)))

class EV_Charger(device.ModbusDevice):
    allowed_roles = None
    default_role = 'evcharger'
    default_instance = 40
    productid = 0xc024
    productname = 'EV Charging Station'

    def __init__(self, *args):
        super(EV_Charger, self).__init__(*args)

        self.info_regs = [
            Reg_text(5001, 6, '/Serial', little=True),
            Reg_ver(5007, '/FirmwareVersion'),
        ]

        self.data_regs = [
            Reg_e16(5009, '/Mode', EVC_MODE, write=True),
            Reg_u16(5010, '/StartStop', write=[0, 1]),
            Reg_u16(5011, '/Ac/L1/Power', 1, '%d W'),
            Reg_u16(5012, '/Ac/L2/Power', 1, '%d W'),
            Reg_u16(5013, '/Ac/L3/Power', 1, '%d W'),
            Reg_u16(5014, '/Ac/Power',    1, '%d W'),
            Reg_e16(5015, '/Status', EVC_STATUS),
            Reg_u16(5016, '/SetCurrent',  1, '%d A', write=True),
            Reg_u16(5017, '/MaxCurrent',  1, '%d A', write=True),
            Reg_u16(5018, '/Current',    10, '%.1f A'),
            Reg_u32b(5019, '/ChargingTime', 1, '%d s'),
            Reg_u16(5021, '/Ac/Energy/Forward', 100, '%.2f kWh'),
        ]

    def get_ident(self):
        return 'evc_%s' % self.info['/Serial']

models = {
    0xc024: {
        'model':    'AC22',
        'handler':  EV_Charger,
    },
}

probe.add_handler(probe.ModelRegister(5000, models,
                                      methods=['tcp'],
                                      units=[1]))
mdns.add_service('_victron-car-charger._tcp')
