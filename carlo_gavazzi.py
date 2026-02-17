import device
import probe
from register import *

class Reg_ver(Reg, str):
    def __init__(self, base, name):
        super().__init__(base, 1, name)

    def decode(self, values):
        v = values[0]
        return self.update('%d.%d.%d' % (v >> 12, v >> 8 & 0xf, v & 0xff))

class Reg_text_et112(Reg, str):
    ''' ET112 serial is U16, but MSB must be ignored '''
    def __init__(self, base, count, name=None, **kwargs):
        super().__init__(base, count, name, **kwargs)
        self.encoding = 'ascii'
        self.pfmt = '%c%dH' % (['>', '<'][True], count)

    def decode(self, values):
        newval = struct.pack(self.pfmt, *values).rstrip(b'\0')
        newval = str(newval.decode(self.encoding))
        newval = newval.replace("\x00", "")
        return self.update(newval)

    def encode(self):
        return struct.unpack(self.pfmt,
            self.value.encode(self.encoding).ljust(2 * self.count, b'\0'))

nr_phases = [ 3, 3, 2, 1, 3 ]

phase_configs = [
    '3P.n',
    '3P.1',
    '2P',
    '1P',
    '3P',
]

phase_configs_et112 = [
    '1P',
]

switch_positions = [
    'kVARh',
    '2',
    '1',
    'Locked',
]

class EM24_Meter(device.CustomName, device.EnergyMeter):
    vendor_id = 'cg'
    vendor_name = 'Carlo Gavazzi'
    productid = 0xb017
    productname = 'Carlo Gavazzi EM24 Ethernet Energy Meter'
    min_timeout = 0.5

    def phase_regs(self, n):
        s = 2 * (n - 1)
        return [
            Reg_s32l(0x0000 + s, '/Ac/L%d/Voltage' % n,        10, '%.1f V'),
            Reg_s32l(0x000c + s, '/Ac/L%d/Current' % n,      1000, '%.1f A'),
            Reg_s32l(0x0012 + s, '/Ac/L%d/Power' % n,          10, '%.1f W'),
            Reg_s32l(0x0040 + s, '/Ac/L%d/Energy/Forward' % n, 10, '%.1f kWh'),
        ]

    def device_init(self):
        self.info_regs = [
            Reg_ver( 0x0302, '/HardwareVersion'),
            Reg_ver( 0x0304, '/FirmwareVersion'),
            Reg_u16( 0x1002, '/PhaseConfig', text=phase_configs, write=(0, 4)),
            Reg_text(0x5000, 7, '/Serial'),
        ]

        # make sure application is set to H
        appreg = Reg_u16(0xa000)
        if self.read_register(appreg) != 7:
            self.write_register(appreg, 7)

            # read back the value in case the setting is not accepted
            # for some reason
            if self.read_register(appreg) != 7:
                self.log.error('%s: failed to set application to H', self)
                return

        self.read_info()

        phases = nr_phases[int(self.info['/PhaseConfig'])]

        regs = [
            Reg_s32l(0x0028, '/Ac/Power',          10, '%.1f W'),
            Reg_u16( 0x0033, '/Ac/Frequency',      10, '%.1f Hz'),
            Reg_s32l(0x0034, '/Ac/Energy/Forward', 10, '%.1f kWh'),
            Reg_s32l(0x004e, '/Ac/Energy/Reverse', 10, '%.1f kWh'),
            Reg_u16( 0xa100, '/SwitchPos', text=switch_positions),
        ]

        if phases == 3:
            regs += [
                Reg_mapu16(0x0032, '/PhaseSequence', { 0: 0, 0xffff: 1 }),
            ]

        for n in range(1, phases + 1):
            regs += self.phase_regs(n)

        self.data_regs = regs
        self.nr_phases = phases

    def dbus_write_register(self, reg, path, val):
        super().dbus_write_register(reg, path, val)
        self.sched_reinit()


class ET112_Meter(device.CustomName, device.EnergyMeter):
    vendor_id = 'cg'
    vendor_name = 'Carlo Gavazzi'
    productid = 0xb00c
    productname = 'Carlo Gavazzi ET112 ModbusTCP Energy Meter'
    min_timeout = 0.5

    def device_init(self):
        self.info_regs = [
            Reg_u16( 0x0302, '/HardwareVersion'),
            Reg_u16( 0x0303, '/FirmwareVersion'),
            Reg_u16( 0x1002, '/PhaseConfig', text=phase_configs_et112),
            Reg_text_et112(0x5000, 7, '/Serial'),
        ]

        # make sure measurement mode is set to 1 (B) for bidirectional
        appreg = Reg_u16(0x1103)
        if self.read_register(appreg) != 1:
            self.write_register(appreg, 1)

            # read back the value in case the setting is not accepted
            # for some reason
            if self.read_register(appreg) != 1:
                self.log.error('%s: failed to set measurement to bidirectional', self)
                return

        self.read_info()

        regs = [
            Reg_s32l(0x0004, '/Ac/Power',             10, '%.1f W'),
            Reg_s16( 0x000F, '/Ac/Frequency',         10, '%.1f Hz'),
            Reg_s16( 0x000E, '/Ac/PowerFactor',     1000, '%.2f'),
            Reg_s32l(0x0010, '/Ac/Energy/Forward',    10, '%.1f kWh'),
            Reg_s32l(0x0020, '/Ac/Energy/Reverse',    -10, '%.1f kWh'),
            Reg_s32l(0x0000, '/Ac/L1/Voltage',        10, '%.1f V'),
            Reg_s32l(0x0002, '/Ac/L1/Current',      1000, '%.1f A'),
            Reg_s32l(0x0004, '/Ac/L1/Power',          10, '%.1f W'),
            Reg_s32l(0x0010, '/Ac/L1/Energy/Forward', 10, '%.1f kWh'),
            Reg_s32l(0x0020, '/Ac/L1/Energy/Reverse', -10, '%.1f kWh'),
        ]

        self.data_regs = regs
        self.nr_phases = 1

    def dbus_write_register(self, reg, path, val):
        super().dbus_write_register(reg, path, val)
        self.sched_reinit()

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
    121: {
        'model':    'ET112DINAV11XS1X',
        'handler':  ET112_Meter,
    },
    120: {
        'model':    'ET112DINAV01XS1X',
        'handler':  ET112_Meter,
    },
}

probe.add_handler(probe.ModelRegister(Reg_u16(0x000b), models,
                                      methods=['tcp'],
                                      units=[1]))
