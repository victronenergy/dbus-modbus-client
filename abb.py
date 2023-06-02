import struct
import device
import probe
from register import Reg, Reg_s32b, Reg_u16, Reg_u32b, Reg_u64b, Reg_text

class Reg_serial(Reg, str):
    """ ABB meters use a 32-bit integer as serial number. Make it a string
        because that is what dbus (and modbus-tcp) expects. """
    def __init__(self, base, name):
        Reg.__init__(self, base, 2, name)

    def decode(self, values):
        v = struct.unpack('>i', struct.pack('>2H', *values))
        return self.update(str(v[0]))

class ABB_Meter(device.CustomName, device.EnergyMeter):
    productid = 0xb033
    min_timeout = 0.5

    def device_init(self):
        self.info_regs = [
            Reg_serial(0x8900, '/Serial'),
            Reg_text(0x8908, 8, '/FirmwareVersion'),
        ]

        self.data_regs = [
            Reg_s32b(0x5B14, '/Ac/Power',          100, '%.1f W'),
            Reg_u16( 0x5B2C, '/Ac/Frequency',      100, '%.1f Hz'),
            Reg_u64b(0x5000, '/Ac/Energy/Forward', 100, '%.1f kWh'),
            Reg_u64b(0x5004, '/Ac/Energy/Reverse', 100, '%.1f kWh', invalid=0xffffffffffffffff),

            # We always have L1 voltage and current
            Reg_u32b(0x5B00, '/Ac/L1/Voltage',      10, '%.1f V'),
            Reg_u32b(0x5B0C, '/Ac/L1/Current',     100, '%.1f A'),
        ]

    def get_ident(self):
        return 'abb_{}'.format(self.info['/Serial'])

class ABB_Meter_1P(ABB_Meter):
    productname = 'ABB B21 Energy Meter'
    nr_phases = 1

    def device_init(self):
        super(ABB_Meter_1P, self).device_init()

        # Copies of overall values, because phase values show not-supported.
        self.data_regs += [
            Reg_s32b(0x5B14, '/Ac/L1/Power',          100, '%.1f W'),
            Reg_u64b(0x5000, '/Ac/L1/Energy/Forward', 100, '%.1f kWh'),
            Reg_u64b(0x5004, '/Ac/L1/Energy/Reverse', 100, '%.1f kWh', invalid=0xffffffffffffffff),
        ]

class ABB_Meter_3P(ABB_Meter):
    productname = 'ABB B23/B24 Energy Meter'
    nr_phases = 3

    def device_init(self):
        super(ABB_Meter_3P, self).device_init()
        self.data_regs += [
            Reg_u32b(0x5B02, '/Ac/L2/Voltage',      10, '%.1f V'),
            Reg_u32b(0x5B04, '/Ac/L3/Voltage',      10, '%.1f V'),
            Reg_u32b(0x5B0E, '/Ac/L2/Current',     100, '%.1f A'),
            Reg_u32b(0x5B10, '/Ac/L3/Current',     100, '%.1f A'),

            Reg_s32b(0x5B16,  '/Ac/L1/Power',       100, '%.1f W'),
            Reg_s32b(0x5B18,  '/Ac/L2/Power',       100, '%.1f W'),
            Reg_s32b(0x5B1A,  '/Ac/L3/Power',       100, '%.1f W'),

            Reg_u64b(0x5460, '/Ac/L1/Energy/Forward', 100, '%.1f kWh'),
            Reg_u64b(0x5464, '/Ac/L2/Energy/Forward', 100, '%.1f kWh'),
            Reg_u64b(0x5468, '/Ac/L3/Energy/Forward', 100, '%.1f kWh'),
            Reg_u64b(0x546C, '/Ac/L1/Energy/Reverse', 100, '%.1f kWh', invalid=0xffffffffffffffff),
            Reg_u64b(0x5470, '/Ac/L2/Energy/Reverse', 100, '%.1f kWh', invalid=0xffffffffffffffff),
            Reg_u64b(0x5474, '/Ac/L3/Energy/Reverse', 100, '%.1f kWh', invalid=0xffffffffffffffff),
        ]

models = {
    0x42323120: { # B21 (space)
        'model':    'B21',
        'handler':  ABB_Meter_1P,
    },
    0x42323320: { # B23 (space)
        'model':    'B23',
        'handler':  ABB_Meter_3P,
    },
    0x42323420: { # B24 (space)
        'model':    'B24',
        'handler':  ABB_Meter_3P,
    }
}

probe.add_handler(probe.ModelRegister(Reg_u32b(0x8960), models,
                                      methods=['rtu', 'tcp'],
                                      units=[1, 2]))
