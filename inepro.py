# SPDX-FileCopyrightText: 2023 Holger Steinhaus
#
# SPDX-License-Identifier: MIT

import device
import logging
import probe
from register import *


log = logging.getLogger()


class PRO380_Meter(device.EnergyMeter):
    """
    Generic driver for the PRO380 meter series. There are a lot of brandings and variants available,
    which are probably working on a similar register map.

    All register information based on https://ineprometering.com/wp-content/uploads/2019/04/PRO380-user-manual-V2.18v6.pdf

    Attention: The Inepro meter has a two-pole RS485 terminal (D+, D-) without any ground pin.
    It therefore does not work with the genuine Victron RS485 cable and requires an INSULATED RS485 adapter!
    Using an non-insulated cable will result in strange communication errors like missing bytes and injected zero bytes.
    """

    productid = 0xb077
    productname = 'PRO380-Mod'

    def __init__(self, *args):
        super(PRO380_Meter, self).__init__(*args)

        self.info_regs = [
            Reg_u32b(0x4000, '/Serial'),
            Reg_u32b(0x4007, '/FirmwareVersion'),
            Reg_u32b(0x4009, '/HardwareVersion'),
        ]

    def phase_regs(self, n):
        s = 2 * (n - 1)
        return [
            Reg_f32b(0x5002 + s, '/Ac/L%d/Voltage' % n,        1, '%.1f V'),
            Reg_f32b(0x500c + s, '/Ac/L%d/Current' % n,        1, '%.1f A'),
            Reg_f32b(0x5014 + s, '/Ac/L%d/Power' % n, scale=0.001, text='%.1f W'),
            Reg_f32b(0x6012 + s, '/Ac/L%d/Energy/Forward' % n, 1.,'%.1f kWh'),
            Reg_f32b(0x601c + s, '/Ac/L%d/Energy/Reverse' % n, 1.,'%.1f kWh'),
        ]

    def device_init(self):
        log.debug("init")
        # make sure application is set to H
        appreg = Reg_u16(0xa000)
        self.read_info()

        phases = 3

        regs = [
            Reg_f32b(0x5008, '/Ac/Frequency',      1., '%.1f Hz'),
            Reg_f32b(0x5012, '/Ac/Power',          0.001, '%.1f W'),
            Reg_f32b(0x502a, '/Ac/PowerFactor',    1, '%.1f'),
            Reg_f32b(0x600c, '/Ac/Energy/Forward', 1., '%.1f kWh'),
            Reg_f32b(0x6018, '/Ac/Energy/Reverse', 1., '%.1f kWh'),
        ]

        for n in range(1, phases + 1):
            regs += self.phase_regs(n)

        self.data_regs = regs

    def dbus_write_register(self, reg, path, val):
        super(PRO380_Meter, self).dbus_write_register(reg, path, val)
        self.sched_reinit()

    def get_ident(self):
        return 'cg_%s' % self.info['/Serial']


models = {
    0x2007: {
        'model':    'SolarLog PRO380-Mod',
        'handler':  PRO380_Meter,
    },
}



probe.add_handler(probe.ModelRegister(Reg_u16(0x1010), models,
                                      methods=['rtu'],
                                      rates=[9600],
                                      units=[1]))
