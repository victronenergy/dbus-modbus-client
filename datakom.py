import struct
import device
import probe
from register import Reg, Reg_u16, Reg_u32l, Reg_mapu16

class Reg_Datakom_ident(Reg, str):
    def __init__(self):
        super().__init__(10609, 1)

    def decode(self, values):
        return self.update(''.join(f'{value:04X}' for value in values))

class Reg_Datakom_serial(Reg, str):
    def __init__(self):
        super().__init__(11687, 6, '/Serial')

    def decode(self, values):
        return self.update(''.join(f'{(value >> 8) | ((value & 0xFF) << 8):04X}' for value in values))

class Reg_Datakom_fw(Reg, str):
    def __init__(self):
        super().__init__(10611, 1, '/FirmwareVersion')

    def decode(self, values):
        return self.update('.'.join(str(values[0])))

class Datakom_Tank(device.CustomName, device.Tank, device.SubDevice):
    raw_value_min = 0
    raw_value_max = 100
    raw_unit = '%'

    def device_init(self):
        self.data_regs = [
            Reg_u16(10363, '/RawValue', 10, '%.0f %%'),
        ]

class Datakom_Generator(device.CustomName, device.Genset):
    vendor_id = 'datakom'
    vendor_name = 'Datakom'
    productid = 0xB04B
    productname = 'Datakom genset controller'
    min_timeout = 0.5
    reg_hole_max = 0

    def device_init(self):
        self.info_regs = [
            Reg_Datakom_serial(),
            Reg_Datakom_fw(),
            Reg_mapu16(321, '/NrOfPhases', {
                0: 2, 1: 2, # Split phase
                2: 3, 3: 3, 4: 3, 5: 3, 6: 3, # 3 phase
                7: 1 # single phase 
            })
        ]

        self.data_regs = [
            Reg_u32l(10628,   '/Ac/Energy/Forward', 10, '%.0f kWh'),
            Reg_u32l(10294,   '/Ac/Power',          0.01, '%.0f W'),
            Reg_u16(10339,    '/Ac/Frequency',      100, '%.1f Hz'),

            Reg_u32l(10270,   '/Ac/L1/Current',     10, '%.0f A'),
            Reg_u32l(10286,   '/Ac/L1/Power',       0.01, '%.0f W'),
            Reg_u32l(10246,   '/Ac/L1/Voltage',     10, '%.0f V'),
            
            Reg_u32l(10272,   '/Ac/L2/Current',     10, '%.0f A'),
            Reg_u32l(10288,   '/Ac/L2/Power',       0.01, '%.0f W'),
            Reg_u32l(10248,   '/Ac/L2/Voltage',     10, '%.0f V'),

            Reg_u32l(10274,   '/Ac/L3/Current',     10, '%.0f A'),
            Reg_u32l(10290,   '/Ac/L3/Power',       0.01, '%.0f W'),
            Reg_u32l(10250,   '/Ac/L3/Voltage',     10, '%.0f V'),

            Reg_mapu16(10605, '/RemoteStartModeEnabled', {
                1: 0, # STOP mode
                2: 1, # RUN/MANUAL mode
                4: 1, # AUTO mode
                8: 0  # TEST mode
            }),

            Reg_u16(10341,     '/StarterVoltage', 100, '%.1f V'),
            Reg_mapu16(10604,  '/StatusCode', {
                0: 0, # genset at rest
                1: 1, # wait before fuel
                2: 1, # engine preheat
                3: 1, # wait oil flash off
                4: 1, # crank rest
                5: 1, # cranking
                6: 8, # engine run idle speed
                7: 8, # engine heating
                8: 8, # running off load
                9: 8, # synchronizing to mains
                10: 8, # load transfer to genset
                11: 8, # gen cb activation
                12: 8, # genset cb timer
                13: 8, # master genset on load
                14: 8, # peak lopping
                15: 8, # power exporting
                16: 8, # slave genset on load
                17: 8, # synchronizing back to mains
                18: 8, # load transfer to mains
                19: 8, # mains cb activation
                20: 8, # mains cb timer
                21: 9, # stop with cooldown
                22: 9, # cooling down
                23: 9, # engine stop idle speed
                24: 9, # immediate stop
                25: 9 # engine stopping
            }),
            
            Reg_u16(10362,     '/Engine/CoolantTemperature', 10, '%.1f C'),
            Reg_u16(10361,     '/Engine/OilPressure',        0.1, '%.0f kPa'),
            Reg_u16(10364,     '/Engine/OilTemperature',     10, '%.1f C', invalid=0x7FFF),
            Reg_u32l(10622,    '/Engine/OperatingHours',     1/36, '%.1f s'),
            Reg_u16(10376,     '/Engine/Speed',              1, '%.0f RPM'),
            Reg_u16(10616,     '/Engine/Starts',             1, '%.0f'),
        ]

        if self.read_register(Reg_u16(10363)) is not None:
            self.subdevices = [
                Datakom_Tank(self, 0),
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
        if value:
            self.write_modbus(8193, [18])
        else:
            self.write_modbus(8193, [4])
        return True

    def _set_remote_start_mode(self, _, value):
        return True

models = {
    'D300': { # D-300
        'model': 'D-300',
        'handler': Datakom_Generator,
    },
    'D500': { # D-500
        'model': 'D-500',
        'handler': Datakom_Generator,
    },
    'D545': { # D-545
        'model': 'D-545',
        'handler': Datakom_Generator,
    },
    'D700': { # D-700
        'model': 'D-700',
        'handler': Datakom_Generator,
    }
}
probe.add_handler(probe.ModelRegister(Reg_Datakom_ident(), models,
                                      methods=['tcp'], units=[1]))
