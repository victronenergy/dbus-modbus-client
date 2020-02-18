from functools import partial

import device
from register import *

CT_TYPES = [
    'SCT01-50A/100A/200A',
    'SCT01-400A/800A',
    'Rogowski coil 600A-100mV',
    'SCT02-50A',
    'SCT02-100A',
    'SCT02-200A',
    'SCT02-400A',
    'SCT02-800A',
    'SCT03-50A',
    'SCT03-100A',
    'SCT03-200A',
    'Rogowski coil 400A-100mV',
    'Closed CT',
]

class Reg_cttype(Reg_uint16):
    def __str__(self):
        if self.value < len(CT_TYPES):
            return CT_TYPES[self.value]
        return str(self.value)

class Reg_ser(Reg_text):
    def __init__(self, base, *args):
        Reg.__init__(self, base, 4, *args)

    def decode(self, values):
        v = '%04d%06d' % (values[0], values[3] << 16 | values[2])
        return self.update(v)

class Reg_ver(Reg, int):
    def __new__(cls, *args):
        return int.__new__(cls)

    def __init__(self, base, *args):
        Reg.__init__(self, base, 2, *args)

    def __int__(self):
        v = self.value
        return v[0] << 16 | v[1] << 8

    def __str__(self):
        return '%d.%d' % self.value

    def decode(self, values):
        return self.update((values[1], values[0]))

class PowerBox(device.EnergyMeter):
    productid = 0xbfff
    productname = 'Smappee Power Box'

    def __init__(self, *args):
        device.ModbusDevice.__init__(self, *args)

        self.info_regs = [
            Reg_ser(  0x1620, '/Serial'),
            Reg_ver(  0x1624, '/FirmwareVersion'),
            Reg_float(0x03f6, '/Ac/FrequencyNominal',  1, '%.0f Hz'),
        ]

        self.data_regs = [
            Reg_float(    0x03f8, '/Ac/Frequency',            1, '%.1f Hz'),
        ]

    def probe_device(self, n):
        base = 0x1480 + 0x20 * n

        regs = [
            Reg_uint16(base + 0x00, '/Device/%d/Type' % n),
            Reg_uint16(base + 0x01, '/Device/%d/Slots' % n),
            Reg_ser(   base + 0x00, '/Device/%d/Serial' % n),
            Reg_ver(   base + 0x04, '/Device/%d/FirmwareVersion' % n),
        ]

        if self.read_register(regs[0]) == 0:
            return 0

        self.info_regs += regs

        return self.read_register(regs[1])

    def probe_ct(self, n):
        regs = [
            Reg_uint16(0x1000 + n, '/CT/%d/Phase' % n),
            Reg_cttype(0x1100 + n, '/CT/%d/Type' % n),
            Reg_uint16(0x1140 + n, '/CT/%d/Slot' % n),
        ]

        if self.read_register(regs[2]) >= self.num_slots:
            return

        phase = self.read_register(regs[0])

        if phase in [1, 16]:    # L1-N
            self.ct_phase[0].append(n)
        elif phase in [2, 32]:  # L2-N
            self.ct_phase[1].append(n)
        elif phase in [4, 64]:  # L3-N
            self.ct_phase[2].append(n)

        self.info_regs += regs

    def add_phase(self, ph, ct):
        n = ph + 1

        self.voltage_regs += [
            Reg_float(0x0000 + 4 * ph, '/Ac/L%d/Voltage' % n, 1, '%.1f V'),
        ]

        self.current_regs += [
            Reg_float(0x0080 + 4 * ct, '/Ac/L%d/Current' % n, 1, '%.1f A'),
        ]

        self.power_regs += [
            Reg_float(0x0380 + 2 * ct, '/Ac/L%d/Power' % n, 1, '%.1f W'),
        ]

        self.energy_regs += [
            Reg_int32(0x3000 + 4 * ct, '/Ac/L%d/Energy/Forward' % n, 1000, '%.1f kWh'),
            Reg_int32(0x3002 + 4 * ct, '/Ac/L%d/Energy/Reverse' % n, 1000, '%.1f kWh')
        ]

    def init_virtual(self):
        mask = 0

        for n in range(3):
            if self.ct_phase[n]:
                mask |= 1 << self.ct_phase[n][0]

        self.write_register(Reg_int32(0x1400), mask)

        self.data_regs += [
            Reg_float(0x03c0, '/Ac/Power', 1, '%.1f W'),
            Reg_int32(0x3100, '/Ac/Energy/Forward', 1000, '%.1f kWh'),
            Reg_int32(0x3102, '/Ac/Energy/Reverse', 1000, '%.1f kWh'),
        ]

    def device_init(self):
        self.num_slots = 0

        for n in range(10):
            self.num_slots += self.probe_device(n)

        self.ct_phase = [[], [], []]
        self.voltage_regs = []
        self.current_regs = []
        self.power_regs = []
        self.energy_regs = []

        for n in range(28):
            self.probe_ct(n)

        for n in range(3):
            if self.ct_phase[n]:
                self.add_phase(n, self.ct_phase[n][0])

        self.current_regs.sort(key=lambda r: r.base)
        self.power_regs.sort(key=lambda r: r.base)
        self.energy_regs.sort(key=lambda r: r.base)

        self.data_regs += [
            self.voltage_regs,
            self.current_regs,
            self.power_regs,
            self.energy_regs,
        ]

        self.init_virtual()

    def ct_identify(self, ct, path, val):
        self.write_register(Reg_uint16(0x0900 + ct), val)
        return False

    def device_init_late(self):
        for ct in self.ct_phase:
            for n in ct:
                cb = partial(self.ct_identify, n)
                self.dbus.add_path('/CT/%d/Identify' % n, None,
                                   writeable=True, onchangecallback=cb)

    def get_ident(self):
        return 'smappee_%s' % self.info['/Serial']

models = {
    5400: {
        'model':    'MOD-VAC-1',
        'handler':  PowerBox,
    },
}

device.add_handler(device.ModelRegister(0x1620, models))
