import device
import probe
from register import *

class Reg_ver(Reg, int):
    def __init__(self, base, name):
        Reg.__init__(self, base, 1, name)

    def __int__(self):
        v = self.value
        return v[0] << 16 | v[1] << 8 | v[2]

    def __str__(self):
        return '%d.%d.%d' % self.value

    def decode(self, values):
        v = values[0]
        return self.update((v >> 12, v >> 8 & 0xf, v & 0xff))

nr_phase_map = {
    0: 3, # 3P.n
    1: 3, # 3P.1
    2: 2, # 2P
    3: 1, # 1P
    4: 3, # 3P
}

switch_positions = [
    'kVARh',
    '2',
    '1',
    'Locked',
]

class EM24_Meter(device.EnergyMeter):
    productid = 0xb017
    productname = 'Carlo Gavazzi EM24 Ethernet Energy Meter'

    def __init__(self, *args):
        super(EM24_Meter, self).__init__(*args)

        self.info_regs = [
            Reg_ver(   0x0302,    '/HardwareVersion'),
            Reg_ver(   0x0304,    '/FirmwareVersion'),
            Reg_mapu16(0x1002,    '/Phases', nr_phase_map),
            Reg_text(  0x5000, 7, '/Serial'),
        ]

    def phase_regs(self, n):
        s = 2 * (n - 1)
        return [
            Reg_s32l(0x0000 + s, '/Ac/L%d/Voltage' % n,        10, '%.1f V'),
            Reg_s32l(0x000c + s, '/Ac/L%d/Current' % n,      1000, '%.1f A'),
            Reg_s32l(0x0012 + s, '/Ac/L%d/Power' % n,          10, '%.1f W'),
            Reg_s32l(0x0040 + s, '/Ac/L%d/Energy/Forward' % n, 10, '%.1f kWh'),
        ]

    def device_init(self):
        self.read_info()

        phases = int(self.info['/Phases'])

        regs = [
            Reg_s32l(0x0028, '/Ac/Power',          10, '%.1f W'),
            Reg_u16( 0x0033, '/Ac/Frequency',      10, '%.1f Hz'),
            Reg_s32l(0x0034, '/Ac/Energy/Forward', 10, '%.1f kWh'),
            Reg_s32l(0x004e, '/Ac/Energy/Reverse', 10, '%.1f kWh'),
            Reg_u16( 0xa100, '/SwitchPos', text=switch_positions),
        ]

        for n in range(1, phases + 1):
            regs += self.phase_regs(n)

        self.data_regs = regs

    def get_ident(self):
        return 'cg_%s' % self.info['/Serial']

models = {
    1648: {
        'model':    'EM24DINAV23XE1X',
        'handler':  EM24_Meter,
    },
    1649: {
        'model':    'EM24DINAV23XE1PFA',
        'handler':  EM24_Meter,
    },
    1650: {
        'model':    'EM24DINAV23XE1PFB',
        'handler':  EM24_Meter,
    },
    1651: {
        'model':    'EM24DINAV53XE1X',
        'handler':  EM24_Meter,
    },
    1652: {
        'model':    'EM24DINAV53XE1PFA',
        'handler':  EM24_Meter,
    },
    1653: {
        'model':    'EM24DINAV53XE1PFB',
        'handler':  EM24_Meter,
    },
}

probe.add_handler(probe.ModelRegister(0x000b, models,
                                      methods=['tcp'],
                                      units=[1]))
