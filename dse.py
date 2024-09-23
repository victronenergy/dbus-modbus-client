import struct

import device
import probe
from register import *

class Reg_DSE_serial(Reg, str):
    """ Deep Sea Electronics Controllers use a 32-bit integer as serial number. Make it a string
        because that is what dbus (and modbus-tcp) expects. """
    def __init__(self, base, name):
        super().__init__(base, 2, name)

    def decode(self, values):
        v = struct.unpack('>I', struct.pack('>2H', *values))
        return self.update(str(v[0]))

class Reg_DSE_ident(Reg, str):
    """ The Deep Sea Electronics controller identifies itself by a combination
        of manufacturer code and model number. The GenComm manual states:

            The manufacturer code and model number must be used together to
            identify a particular product unambiguously.

        Therefore we concatenate manufacturer code and model number to a
        dash-separated string. """
    def __init__(self):
        super().__init__(768, 2)

    def decode(self, values):
        manufacturer_code = values[0]
        model_number = values[1]
        ident_str = f"{ manufacturer_code }-{ model_number }"
        return self.update(ident_str)

INVALID = [
    -1,     # Unimplemented
    -2,     # Over measurable range
    -3,     # Under measurable range
    -4,     # Transducer fault
    -5,     # Bad data
    -6,     # High digital input
    -7,     # Low digital input
    -8,     # Reserved
]

class Reg_DSE_num:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.invalid:
            self.invalid = [x & self.invalid_mask for x in INVALID]

class Reg_DSE_s16(Reg_DSE_num, Reg_s16):
    invalid_mask = 0x7fff

class Reg_DSE_u16(Reg_DSE_num, Reg_u16):
    invalid_mask = 0xffff

class Reg_DSE_s32b(Reg_DSE_num, Reg_s32b):
    invalid_mask = 0x7fffffff

class Reg_DSE_u32b(Reg_DSE_num, Reg_u32b):
    invalid_mask = 0xffffffff

class DSE_Tank(device.CustomName, device.Tank, device.SubDevice):
    raw_value_min = 0
    raw_value_max = 100
    raw_unit = '%'

    def device_init(self):
        self.data_regs = [
            Reg_DSE_u16(1027, '/RawValue', 1, '%.0f %%'),
        ]

class DSE_Generator(device.CustomName, device.ErrorId, device.Genset):
    vendor_id = 'dse'
    vendor_name = 'Deep Sea Electronics'
    productid = 0xB046
    productname = 'DSE genset controller'
    min_timeout = 1         # Increased timeout for less corrupted messages

    init_status_code = None
    has_remote_start = None

    # GenComm System Control Function keys
    SCF_SELECT_AUTO_MODE = 35701     # Select Auto mode
    SCF_TELEMETRY_START  = 35732     # Telemetry start if in auto mode
    SCF_TELEMETRY_STOP   = 35733     # Cancel telemetry start in auto mode

    # Stores 8 register values which indicate of a regarding
    # GenComm System Control Functions is available
    scf_reg_vals = None

    alarm_level = {
        2: 'w',     # Warning alarm
        3: 'e',     # Shutdown alarm
        4: 'e',     # Electrical trip alarm
    }

    def __init__(self, *args):
        super().__init__(*args)

        self.status_reg = Reg_mapu16(1408, '/StatusCode', {
            0: 0,  # Engine stopped = Stopped
            1: 2,  # Pre-Start = Preheat
            2: 8,  # Warming up = Running
            3: 8,  # Running
            4: 9,  # Cooling down = Stopping
            5: 0,  # Engine Stopped
            6: 0,  # Post run = Stopped
            15: 10 # Not available = Error
        })

        self.engine_speed_reg = Reg_DSE_u16(1030, '/Engine/Speed', 1, '%.0f RPM')

        self.info_regs = [
            Reg_DSE_serial(770, '/Serial'),
        ]

    def _write_scf_key(self, scf_key):
        # Controlling the genset is possible by writing the regarding
        # `GenComm System Control Function` key together with its
        # two's-compliment (65535 - key) into register 4104 and 4105.
        # Be aware: Not every device supports the same control keys!
        self.write_modbus(4104, [scf_key, 65535 - scf_key])

    def _read_scf_registers(self):
        if self.scf_reg_vals is not None: return

        reg_base = 4096
        rr = self.modbus.read_holding_registers(reg_base, 8, unit=self.unit)
        if rr.isError():
            self.log.error('Error reading GenComm system control function registers 4096 to 4103: %s', rr)
            raise Exception(rr)
        self.scf_reg_vals = rr.registers

    def _check_scf_support(self, *args):
        # Register 4096 to 4103 contain binary flags for each `GenComm System
        # Control Function` indicating if it is available on this controller
        # unit.
        scf_keys = args

        # Read registers, which contain bit-wise flags
        self._read_scf_registers()

        for key in scf_keys:
            function_code = key - 35700
            idx = function_code // 16
            register_value = self.scf_reg_vals[idx]
            # code 0 is indicated by last bit position, code 1 is
            # indicated by second last, ...
            bit_pos = 15 - function_code % 16

            if not (register_value >> bit_pos) & 1:
                return False
        return True

    def _get_alarm_codes(self, values):
        for v in enumerate(values):
            level = self.alarm_level.get(v[1], None)
            if level:
                yield (level, self.alarm_code_offset + v[0])

    def alarm_changed(self, reg):
        self.set_error_ids(self._get_alarm_codes(reg.value))

    def device_init(self):

        self.data_regs = [
            Reg_DSE_s32b(1536, '/Ac/Power',           1, '%.0f W'),     # Might only work for 61xx MkII and 8xxx/7xxx/6xxx/P100/L40x/4xxx
            Reg_DSE_s32b(1052, '/Ac/L1/Power',        1, '%.0f W'),
            Reg_DSE_s32b(1054, '/Ac/L2/Power',        1, '%.0f W'),
            Reg_DSE_s32b(1056, '/Ac/L3/Power',        1, '%.0f W'),
            Reg_DSE_u32b(1032, '/Ac/L1/Voltage',     10, '%.0f V'),
            Reg_DSE_u32b(1034, '/Ac/L2/Voltage',     10, '%.0f V'),
            Reg_DSE_u32b(1036, '/Ac/L3/Voltage',     10, '%.0f V'),
            Reg_DSE_u32b(1044, '/Ac/L1/Current',     10, '%.0f A'),
            Reg_DSE_u32b(1046, '/Ac/L2/Current',     10, '%.0f A'),
            Reg_DSE_u32b(1048, '/Ac/L3/Current',     10, '%.0f A'),
            Reg_DSE_u32b(1800, '/Ac/Energy/Forward', 10, '%.0f kWh'),   # Might only work for xxx/7xxx/6xxx/L40x/4xxx
            Reg_DSE_u16(1031,  '/Ac/Frequency',      10, '%.1f Hz'),

            self.engine_speed_reg,
            Reg_DSE_s16(1025,  '/Engine/CoolantTemperature',  1, '%.1f C'),
            Reg_DSE_u16(1024,  '/Engine/OilPressure',         1, '%.0f kPa'),
            Reg_DSE_s16(1026,  '/Engine/OilTemperature',      1, '%.0f C'),
            Reg_DSE_s16(1558,  '/Engine/Load',               10, '%.0f %%'),    # Might only work for 61xx MkII and 8xxx/7xxx/6xxx/P100/L40x/4xxx
            Reg_DSE_u32b(1798, '/Engine/OperatingHours',      1, '%.1f s'),     # Might only work for xxx/7xxx/6xxx/L40x/4xxx
            Reg_DSE_u32b(1808, '/Engine/Starts',              1, '%.0f'),       # Might only work for 8xxx/7xxx/6xxx/L40x/4xxx

            Reg_DSE_u16(1029, '/StarterVoltage',            10, '%.1f V'),

            Reg_mapu16(772, '/RemoteStartModeEnabled', {
                0: 0, # Stop mode
                1: 1, # Auto mode
                2: 0, # Manual mode
                3: 0, # Test on load mode
                4: 1, # Auto with manual restore mode
                5: 0, # User configuration mode
                6: 0, # Test off load mode
                7: 0, # Off mode
            }),
            Reg_packed(self.alarm_base, self.alarm_count, bits=4, items=4,
                       onchange=self.alarm_changed)
        ]

        # Check, if status register is implemented on controller
        self.init_status_code = self.read_register(self.status_reg)
        if self._status_register_available():
            self.data_regs.append(self.status_reg)
        else:
            self.log.info('DSE status code register is not available')

        if self.read_register(Reg_DSE_u16(1027)) is not None:
            self.subdevices = [
                DSE_Tank(self, 0),
            ]

    def _status_register_available(self):
        return self.init_status_code is not None


    def _get_status_code_from_rpm(self, rpm=None):
        if rpm is None: rpm = self.engine_speed_reg.value
        if rpm is None: return None
        return 8 if rpm > 100 else 0


    def device_init_late(self):
        super().device_init_late()

        # Additional static paths
        if '/FirmwareVersion' not in self.dbus:
            self.dbus.add_path('/FirmwareVersion', None)

        is_running = None

        # If status register is not available, detect status by rpm value
        if self._status_register_available():
            is_running = self.init_status_code > 0
        else:
            engine_speed_reg_val = self.read_register(self.engine_speed_reg)
            if engine_speed_reg_val is None:
                self.log.error('Cannot detect engine status by RPM, as register is not available')
            else:
                self.log.info('Detecting engine status by RPM')
                status_code = self._get_status_code_from_rpm(engine_speed_reg_val)
                self.dbus.add_path(
                    '/StatusCode',
                    status_code
                )
                is_running = status_code > 0

        # Add /Start path, if GenComm System Control Functions
        # for genset telemetry start are available
        if self.has_remote_start is None:
            self.has_remote_start = self._check_scf_support(self.SCF_TELEMETRY_START, self.SCF_TELEMETRY_STOP)

        if self.has_remote_start:
            self.dbus.add_path(
                '/Start',
                1 if is_running else 0,
                writeable=True,
                onchangecallback=self._start_genset
            )

        # Add /EnableRemoteStartMode path, if GenComm System Control Function
        # for setting into Auto Mode (DSE terminology) is available
        # (depends on DSE controller model)
        if self._check_scf_support(self.SCF_SELECT_AUTO_MODE):
            self.dbus.add_path(
                '/EnableRemoteStartMode',
                0,
                writeable=True,
                onchangecallback=self._set_remote_start_mode
            )

    def device_update(self):
        super().device_update()

        if not self._status_register_available() and self.dbus['/StatusCode'] is not None:
            self.dbus['/StatusCode'] = self._get_status_code_from_rpm()


    def _start_genset(self, path, value):
        if value:
            self._write_scf_key(self.SCF_TELEMETRY_START)
        else:
            self._write_scf_key(self.SCF_TELEMETRY_STOP)
        return True

    def _set_remote_start_mode(self, _, value):
        if value == 1:
            self._write_scf_key(self.SCF_SELECT_AUTO_MODE)
        return True

class DSE4xxx_Generator(DSE_Generator):
    """ This uses the "old alarm system" of GenComm page 8,
        related error strings allocate 0x1000 to 0x10FF """
    alarm_base = 2049
    alarm_count = 25
    alarm_code_offset = 0x1000

class DSE71xx_66xx_60xx_L40x_4xxx_45xx_MkII_Generator(DSE_Generator):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 71xx/66xx/60xx/L40x/4xxx/45xx MkII family, related
        error strings allocate 0x1500 to 0x15FF """
    alarm_base = 39425
    alarm_count = 11
    alarm_code_offset = 0x1500

class DSE61xx_MkII_Generator(DSE_Generator):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 61xx MkII, related error strings allocate 0x1100 to 0x11FF """
    alarm_base = 39425
    alarm_count = 15
    alarm_code_offset = 0x1100

class DSE72xx_73xx_61xx_74xx_MkII_Generator(DSE_Generator):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 72xx/73xx/61xx/74xx MkII family, related error strings
        allocate 0x1200 to 0x12FF """
    alarm_base = 39425
    alarm_count = 20
    alarm_code_offset = 0x1200

class DSE8xxx_Generator(DSE_Generator):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 8xxx family, related error strings allocate 0x1300 to 0x13FF """
    alarm_base = 39425
    alarm_count = 39
    alarm_code_offset = 0x1300

class DSE4520_MKII(DSE71xx_66xx_60xx_L40x_4xxx_45xx_MkII_Generator):
    """ DSE 4520 MKII is a special case, as it reports support for
        Telemetry Start and Stop, but actually does not support that """
    has_remote_start = False

models = {
    '1-4623': {
        'model':    '4620/4623',
        'handler':  DSE4xxx_Generator,
    },
    '1-32808': {
        'model':    '4510 MKII',
        'handler':  DSE71xx_66xx_60xx_L40x_4xxx_45xx_MkII_Generator,
    },
    '1-32807': {
        'model':    '4520 MKII',
        'handler':  DSE4520_MKII,
    },
    '1-32800': {
        'model':    '6110 MKII',
        'handler':  DSE61xx_MkII_Generator,
    },
    '1-6121': {
        'model':    '6120',
        'handler':  DSE4xxx_Generator,
    },
    '1-32859': {
        'model':    '6120 MKIII',
        'handler':  DSE61xx_MkII_Generator,
    },
    '1-32840': {
        'model':    '7310 MKII',
        'handler':  DSE72xx_73xx_61xx_74xx_MkII_Generator,
    },
    '1-32845': {
        'model':    '7410 MKII',
        'handler':  DSE72xx_73xx_61xx_74xx_MkII_Generator,
    },
    '1-32846': {
        'model':    '7420 MKII',
        'handler':  DSE72xx_73xx_61xx_74xx_MkII_Generator,
    },
    '1-32832': {
        'model':    '8610 MKII',
        'handler':  DSE8xxx_Generator,
    },
    '1-32833': {
        'model':    '8620 MKII',
        'handler':  DSE8xxx_Generator,
    },
    '1-32834': {
        'model':    '8660 MKII',
        'handler':  DSE8xxx_Generator,
    },
}


probe.add_handler(probe.ModelRegister(Reg_DSE_ident(), models,
                                      methods=['tcp'], units=[1]))
