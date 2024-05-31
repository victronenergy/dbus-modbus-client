from enum import IntEnum
import struct

import device
import mdns
import probe
from register import *
from victron_regs import *

class EVC_MODE(IntEnum):
    MANUAL          = 0
    AUTO            = 1
    SCHEDULED       = 2

class EVC_CHARGE(IntEnum):
    DISABLED = 0
    ENABLED  = 1

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
    CP_SHORTED      = 10
    EARTH_LEAKAGE   = 11
    UNDERVOLTAGE    = 12
    OVERVOLTAGE     = 13
    OVERTEMPERATURE = 14
    STARTCHARGE     = 21
    SWITCH_TO_3P    = 22
    SWITCH_TO_1P    = 23

class EVC_POSITION(IntEnum):
    OUTPUT = 0
    INPUT = 1

class EV_Charger(device.ModbusDevice):
    vendor_id = 've'
    vendor_name = 'Victron Energy'
    device_type = 'EV charger'
    allowed_roles = None
    default_role = 'evcharger'
    default_instance = 40
    productname = 'EV Charging Station'
    min_timeout = 0.5

    def device_init(self):
        self.info_regs = [
            Reg_text(5001, 6, '/Serial', little=True),
            VEReg_ver(5007, '/FirmwareVersion'),
            Reg_text(5027, 22, '/CustomName', little=True, encoding='utf-8'),
        ]

        self.data_regs = [
            Reg_e16(5009, '/Mode', EVC_MODE, write=True),
            Reg_e16(5010, '/StartStop', EVC_CHARGE, write=True),
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
            Reg_e16(5026, '/Position', EVC_POSITION, write=True),
            Reg_text(5027, 22, '/CustomName', little=True, encoding='utf-8', write=True),
            Reg_u16(5049, '/AutoStart', write=(0,1))
        ]

        fwver = self.read_register(self.info_regs[1])

        # Firmware check, before 1.21~1 we could only fetch 50 registers
        if fwver < (0, 0x01, 0x21, 0x01):
            return

        if self.have_display:
            self.data_regs.append(
                Reg_u16(5050, '/EnableDisplay', write=(0, 1)))

        if fwver < (0, 0x01, 0x22, 0x02):
            return

        self.data_regs += [
            Reg_u16(5062, '/MinCurrent',  1, '%d A', write=True)
        ]

    def get_ident(self):
        return 'evc_%s' % self.info['/Serial']

class EV_Charger_AC22(EV_Charger):
    productid = 0xc024
    have_display = False

class EV_Charger_AC22E(EV_Charger):
    productid = 0xc025
    have_display = True

class EV_Charger_AC22NS(EV_Charger):
    productid = 0xc026
    have_display = False

class EV_Charger_AC22_V2(EV_Charger):
    productid = 0xc023
    have_display = True

class EV_Charger_AC22_V2_NS(EV_Charger):
    productid = 0xc027
    have_display = False

models = {
    EV_Charger_AC22.productid: {
        'model':    'AC22',
        'handler':  EV_Charger_AC22,
    },
    EV_Charger_AC22E.productid: {
        'model':    'AC22E',
        'handler':  EV_Charger_AC22E,
    },
    EV_Charger_AC22NS.productid: {
        'model':    'AC22NS',
        'handler':  EV_Charger_AC22NS,
    },
    EV_Charger_AC22_V2.productid: {
        'model':    'EVCS 32A V2',
        'handler':  EV_Charger_AC22_V2,
    },
    EV_Charger_AC22_V2_NS.productid: {
        'model':    'EVCS 32A NS V2',
        'handler':  EV_Charger_AC22_V2_NS,
    },
}

probe.add_handler(probe.ModelRegister(Reg_u16(5000), models,
                                      methods=['tcp'],
                                      units=[1]))
mdns.add_service('_victron-car-charger._tcp')
