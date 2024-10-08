import device
import probe
from register import Reg, Reg_u16, Reg_s16, Reg_u32l, Reg_mapu16, Reg_text

"""
With the current controller firmware v2.40, there is no reliant way to
detect via Modbus TCP if a fuel tank sensor is connected to one of the
analog inputs, therefore tank readings are currently not supported.
"""

class Reg_CRE_ident(Reg, str):
    PLATFORM_TYPE = {
        '0': 'COMPACT',  # COMPACT (56)
        '1': 'ENHANCED'  # ENHANCED (66)
    }

    PRODUCT_FAMILY = {
        '00': 'PRIME',
        '01': 'MAINS',
        '02': 'SYNCH',
        '03': 'ILS',
        '04': 'PMS',
        '05': 'AMF',
        '06': 'MAST',
        '07': 'MAS1B',
        '08': 'BTB',
        '09': 'PV',
        '10': 'BAT'
    }

    def __init__(self):
        super().__init__(4, 3)

    def decode(self, values):
        s = [ str(v).zfill(5) for v in values ]

        pltfrm_typ = s[0][0]
        prod_fam   = s[2][0:2]
        week       = s[0][1:3]

        if int(week) in range(1, 54) \
            and pltfrm_typ in self.PLATFORM_TYPE \
            and prod_fam in self.PRODUCT_FAMILY:
            return self.update(
                self.PLATFORM_TYPE[pltfrm_typ] + '-' + self.PRODUCT_FAMILY[prod_fam]
            )
        else:
            return self.update(None)

class Reg_CRE_serial(Reg, str):
    def __init__(self):
        super().__init__(4, 3, '/Serial')

    def decode(self, values):
        s = [ str(v).zfill(5) for v in values ]

        week = s[0][1:3]
        year = s[0][3:5]
        production_nr = s[2][2:5]

        return self.update(f"{ week }{ year }_{ production_nr }")

class CRE_Compact_Generator(device.CustomName, device.ErrorId, device.Genset):
    vendor_id = 'cre'
    vendor_name = 'CRE Technology'
    productid = 0xB048
    productname = 'CRE genset controller'
    min_timeout = 0.5
    reg_barrier = (77, 360, 361, 362, 4002, 4003, 4004, 4005)
    max_errors = 2

    def alarm_changed(self, reg):
        eids = []

        if reg.value[0]:
            eids.append(('e', 0))
        if reg.value[1]:
            eids.append(('w', 1))

        self.set_error_ids(eids)

    def device_init(self):
        self.info_regs = [
            Reg_CRE_serial(),
            Reg_text(0, 4, '/FirmwareVersion'),
            Reg_mapu16(2003, '/NrOfPhases', {
                0: 1,                   # single phase
                1: 2,                   # Split phase
                2: 3, 3: 3, 4: 3, 5: 3  # 3 phase
            }),
        ]

        self.data_regs = [
            Reg_s16(363, '/Ac/L1/Power',   1/100,   '%.0f W'),
            Reg_s16(364, '/Ac/L2/Power',   1/100,   '%.0f W'),
            Reg_s16(365, '/Ac/L3/Power',   1/100,   '%.0f W'),
            Reg_u16(50,  '/Ac/L1/Voltage',     1,   '%.0f V'),
            Reg_u16(51,  '/Ac/L2/Voltage',     1,   '%.0f V'),
            Reg_u16(52,  '/Ac/L3/Voltage',     1,   '%.0f V'),
            Reg_u16(59,  '/Ac/L1/Current',     1,   '%.0f A'),
            Reg_u16(60,  '/Ac/L2/Current',     1,   '%.0f A'),
            Reg_u16(61,  '/Ac/L3/Current',     1,   '%.0f A'),
            Reg_u16(75,  '/Ac/Frequency',      100, '%.1f Hz'),

            Reg_u16(78,  '/Engine/Starts',           1,      '%.0f'),
            Reg_u32l(79, '/Ac/Energy/Forward',       1,      '%.0f kWh'),
            Reg_u32l(83, '/Engine/OperatingHours',   1/3600, '%.1f s'),

            Reg_u16(200, '/Engine/OilPressure',         1/10,   '%.0f kPa'),
            Reg_s16(201, '/Engine/CoolantTemperature',  10,     '%.1f C'),
            Reg_u16(202, '/Engine/Speed',               1,      '%.0f RPM'),
            Reg_s16(358, '/Engine/Load',                10,     '%.0f %%'),
            Reg_u16(204, '/StarterVoltage',             10,     '%.1f V'),

            Reg_mapu16(4001, '/StatusCode', {
                0:   0,     # Waiting
                2:   3,     # Start
                3:   2,     # Warm-up
                4:   3,     # Ck. speed stab
                5:   3,     # Ck. volt. stab
                6:   8,     # GE. ready
                7:   8,     # Opening GE
                8:   9,     # Cool down
                9:   9,     # Stop
                11:  0,     # Rest
                12:  3,     # Pre-Start
                13:  3,     # Wait other eng
                14:  3,     # Closing GE
                20:  3,     # Starter only
                21:  3,     # Ignition ON
                22:  3,     # Start
                23:  9,     # Ignition only
                40:  3,     # Ext. Start seq
                255: 10,    # Fault
            }),

            Reg_mapu16(4008, '/RemoteStartModeEnabled', {
                0: 0,  # MAN
                1: 0,  # TEST
                2: 1,  # AUTO
            }),

            Reg(4664, 2, onchange=self.alarm_changed),
        ]

    def device_init_late(self):
        super().device_init_late()

        self.dbus.add_path(
            '/Start',
            0,
            writeable=True,
            onchangecallback=self._start_genset
        )

        self.dbus.add_path(
            '/EnableRemoteStartMode',
            0,
            writeable=True,
            onchangecallback=self._set_remote_start_mode
        )

    def _start_genset(self, _, value):
        # Remote start on load [4502]
        # Activation will start generator in automatic mode and close
        # the generator breaker on load
        self.write_modbus(4502, [bool(value)])
        return True

    def _set_remote_start_mode(self, _, value):
        if value == 1:
            self.write_modbus(4513, [1])
        return False

models = {
    'COMPACT-AMF': {            # A56-AMF-00 & A56-AMF-10
        'model':    'Compact AMF',
        'handler':  CRE_Compact_Generator,
    },
    'COMPACT-PRIME': {          # A56-PRIME-00 & A56-PRIME-10
        'model':    'Gensys Compact Prime',
        'handler':  CRE_Compact_Generator,
    },
    'COMPACT-MAINS': {          # A56-MAINS-00 & A56-MAINS-10
        'model':    'Gensys Compact Mains',
        'handler':  CRE_Compact_Generator,
    },
}

probe.add_handler(probe.ModelRegister(Reg_CRE_ident(), models,
                                      methods=['tcp'], units=[1]))
