import device
from register import *

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
            [
                Reg_float(0x0000, '/Ac/L1/Voltage',           1, '%.1f V'),
                Reg_float(0x0004, '/Ac/L2/Voltage',           1, '%.1f V'),
                Reg_float(0x0008, '/Ac/L3/Voltage',           1, '%.1f V'),
            ],
            [
                Reg_float(0x0080, '/Ac/L1/Current',           1, '%.1f A'),
                Reg_float(0x0084, '/Ac/L2/Current',           1, '%.1f A'),
                Reg_float(0x0088, '/Ac/L3/Current',           1, '%.1f A'),
            ],
            [
                Reg_float(0x0100, '/Ac/L1/Power',             1, '%.1f W'),
                Reg_float(0x0102, '/Ac/L2/Power',             1, '%.1f W'),
                Reg_float(0x0104, '/Ac/L3/Power',             1, '%.1f W'),
            ],
            [
                Reg_float(0x3000, '/Ac/L1/Energy/Forward', 1000, '%.1f kWh'),
                Reg_float(0x3002, '/Ac/L1/Energy/Reverse', 1000, '%.1f kWh'),
                Reg_float(0x3004, '/Ac/L2/Energy/Forward', 1000, '%.1f kWh'),
                Reg_float(0x3006, '/Ac/L2/Energy/Reverse', 1000, '%.1f kWh'),
                Reg_float(0x3008, '/Ac/L3/Energy/Forward', 1000, '%.1f kWh'),
                Reg_float(0x300a, '/Ac/L3/Energy/Reverse', 1000, '%.1f kWh'),
            ],
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

    def device_init(self):
        self.num_slots = 0

        for n in range(10):
            self.num_slots += self.probe_device(n)

    def get_ident(self):
        return 'smappee_%s' % self.info['/Serial']

models = {
    5400: {
        'model':    'MOD-VAC-1',
        'handler':  PowerBox,
    },
}

device.add_handler(device.ModelRegister(0x1620, models))
