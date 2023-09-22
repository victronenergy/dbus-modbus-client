import logging
import struct

import device
import probe
from register import Reg, Reg_s16, Reg_u16, Reg_s32b, Reg_u32b, Reg_mapu16

from pymodbus.register_read_message import ReadHoldingRegistersResponse

log = logging.getLogger()


class Reg_DSE_serial(Reg, str):
    """ Deep Sea Electronics Controllers use a 32-bit integer as serial number. Make it a string
        because that is what dbus (and modbus-tcp) expects. """
    def __init__(self, base, name):
        Reg.__init__(self, base, 2, name)

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
        Reg.__init__(self, 768, 2)
        self.coding = ('H', 'H')

    def decode(self, values):
        manufacturer_code = struct.unpack(self.coding[0], struct.pack(self.coding[1], values[0]))[0]
        model_number = struct.unpack(self.coding[0], struct.pack(self.coding[1], values[1]))[0]
        ident_str = f"{ manufacturer_code }-{ model_number }"
        return self.update(ident_str)

class Reg_DSE_s16(Reg_s16):
    def __init__(self, base, *args, **kwargs):
        super(Reg_DSE_s16, self).__init__(base, *args, **kwargs)
        if not self.invalid:
            # DSE GenComm defines the following non-numeric `Sentinel values for instrumentation`
            self.invalid = [
                0x7FFF, # Unimplemented
                0x7FFE, # Over measurable range
                0x7FFD, # Under measurable range
                0x7FFC, # Transducer fault
                0x7FFB, # Bad data
                0x7FFA, # High digital input
                0x7FF9, # Low digital input
                0x7FF8  # Reserved
            ]

class Reg_DSE_u16(Reg_u16):
    def __init__(self, base, *args, **kwargs):
        super(Reg_DSE_u16, self).__init__(base, *args, **kwargs)
        if not self.invalid:
            self.invalid = [
                0xFFFF, # Unimplemented
                0xFFFE, # Over measurable range
                0xFFFD, # Under measurable range
                0xFFFC, # Transducer fault
                0xFFFB, # Bad data
                0xFFFA, # High digital input
                0xFFF9, # Low digital input
                0xFFF8  # Reserved
            ]

class Reg_DSE_s32b(Reg_s32b):
    def __init__(self, base, *args, **kwargs):
        super(Reg_DSE_s32b, self).__init__(base, *args, **kwargs)
        if not self.invalid:
            self.invalid = [
                0x7FFFFFFF, # Unimplemented
                0x7FFFFFFE, # Over measurable range
                0x7FFFFFFD, # Under measurable range
                0x7FFFFFFC, # Transducer fault
                0x7FFFFFFB, # Bad data
                0x7FFFFFFA, # High digital input
                0x7FFFFFF9, # Low digital input
                0x7FFFFFF8  # Reserved
            ]

class Reg_DSE_u32b(Reg_u32b):
    def __init__(self, base, *args, **kwargs):
        super(Reg_DSE_u32b, self).__init__(base, *args, **kwargs)
        if not self.invalid:
            self.invalid = [
                0xFFFFFFFF, # Unimplemented
                0xFFFFFFFE, # Over measurable range
                0xFFFFFFFD, # Under measurable range
                0xFFFFFFFC, # Transducer fault
                0xFFFFFFFB, # Bad data
                0xFFFFFFFA, # High digital input
                0xFFFFFFF9, # Low digital input
                0xFFFFFFF8  # Reserved
            ]

class Reg_DSE_alarm(Reg, int):
    """ Decode DSE alarm registers into error codes, which
        are offset for correct error string mapping """

    def __init__(self, base, count, error_code_offset):
        # Note: Base register has to be first on GenComm page
        # definition ("Number of named alarms")
        Reg.__init__(self, base=base, count=count, name='/ErrorCode')
        self.error_code_offset = error_code_offset
        self.coding = ('H', 'H')

    def _interpret_alarm_value(self, val):
        """ Meaning according to GenComm specification: 
            0      Disabled digital input
            1      Not active alarm
            2      Warning alarm
            3      Shutdown alarm
            4      Electrical trip alarm
            5-7    Reserved
            8      Inactive indication (no string)
            9      Inactive indication (displayed string)
            10     Active indication
            11-14  Reserved
            15     Unimplemented alarm """
        if val == 1: return False
        if 2 <= val <= 4: return True
        return None

    def _decode_into_4bits(self, z):
        """ Splits register value into four 4 bit integers and interprets the
            numbers """
        vals = [
            z >> 12 & 0xF,
            z >> 8 & 0xF,
            z >> 4 & 0xF,
            z & 0xF
        ]
        return map(self._interpret_alarm_value, vals)

    def _decode_alarm_registers(self, values):
        """ Returns a list of all alarms with bool or None values
            True indicates active alarm,
            False indicates inactive alarm,
            None indicates an unimplemented or unknown alarm state """
        alarms = list()
        for reg_val in values:
            v = struct.unpack(self.coding[0], struct.pack(self.coding[1], reg_val))
            alarms.extend(self._decode_into_4bits(v[0]))
        return alarms

    def decode(self, values):
        alarms = self._decode_alarm_registers(values[1:])
        try:
            # if multiple alarms firing, only first one is displayed
            alarm_idx = self.error_code_offset + alarms.index(True)
            return self.update(alarm_idx)
        except ValueError:
            # No alarms firing
            return self.update(0)


class Reg_DSE_alarm_old_system(Reg_DSE_alarm):
    """ This uses the "old alarm system" of GenComm page 8,
        related error strings allocate 0x1000 to 0x10FF """
    def __init__(self):
        super(Reg_DSE_alarm_old_system, self).__init__(
            base=2048,
            count=26,
            error_code_offset=0x1000
        )

class Reg_DSE_alarm_61xx_MkII(Reg_DSE_alarm):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 61xx MkII, related error strings allocate 0x1100 to 0x11FF """
    def __init__(self):
        super(Reg_DSE_alarm_61xx_MkII, self).__init__(
            base=39424,
            count=16,
            error_code_offset=0x1100
        )

class Reg_DSE_alarm_72xx_73xx_61xx_74xx_MkII(Reg_DSE_alarm):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 72xx/73xx/61xx/74xx MkII family, related error strings
        allocate 0x1200 to 0x12FF """
    def __init__(self):
        super(Reg_DSE_alarm_72xx_73xx_61xx_74xx_MkII, self).__init__(
            base=39424,
            count=21,
            error_code_offset=0x1200
        )

class Reg_DSE_alarm_8xxx(Reg_DSE_alarm):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 8xxx family, related error strings allocate 0x1300 to 0x13FF """
    def __init__(self):
        super(Reg_DSE_alarm_8xxx, self).__init__(
            base=39424,
            count=40,
            error_code_offset=0x1300
        )

class Reg_DSE_alarm_7450(Reg_DSE_alarm):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 7540, related error strings allocate 0x1400 to 0x14FF """
    def __init__(self):
        super(Reg_DSE_alarm_7450, self).__init__(
            base=39424,
            count=28,
            error_code_offset=0x1400
        )

class Reg_DSE_alarm_71xx_66xx_60xx_L40x_4xxx_45xx_MkII(Reg_DSE_alarm):
    """ This uses "Named Alarm Conditions" of GenComm page 154 for
        DSE 71xx/66xx/60xx/L40x/4xxx/45xx MkII family, related
        error strings allocate 0x1500 to 0x15FF """
    def __init__(self):
        super(Reg_DSE_alarm_71xx_66xx_60xx_L40x_4xxx_45xx_MkII, self).__init__(
            base=39424,
            count=12,
            error_code_offset=0x1500
        )


class DSE_Generator(device.CustomName, device.ModbusDevice):
    productid = 0xB046
    productname = 'Deep Sea Electronics genset controller'
    allowed_roles = None
    default_role = 'genset'
    default_instance = 40
    min_timeout = 1         # Increased timeout for less corrupted messages

    detect_status_by_rpm = False

    # GenComm System Control Function keys
    SCF_SELECT_AUTO_MODE = 35701     # Select Auto mode
    SCF_TELEMETRY_START  = 35732     # Telemetry start if in auto mode
    SCF_TELEMETRY_STOP   = 35733     # Cancel telemetry start in auto mode

    # Stores 8 register values which indicate of a regarding
    # GenComm System Control Functions is available
    scf_reg_vals = None

    def __init__(self, *args):
        super(DSE_Generator, self).__init__(*args)

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
        if not isinstance(rr, ReadHoldingRegistersResponse):
            log.error('Error reading GenComm system control function registers 4096 to 4103: %s', rr)
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

            Reg_DSE_u16(1027, '/FuelLevel',                  1, '%.0f %%'),
            Reg_DSE_u16(1029, '/StarterVoltage',            10, '%.1f V'),

            Reg_mapu16(772, '/AutoStart', {
                0: 0, # Stop mode
                1: 1, # Auto mode
                2: 0, # Manual mode
                3: 0, # Test on load mode
                4: 1, # Auto with manual restore mode
                5: 0, # User configuration mode
                6: 0, # Test off load mode
                7: 0, # Off mode
            }),
        ]


    def get_ident(self):
        return 'dse_%s' % self.info['/Serial']


    def _get_status_code_from_rpm(self, rpm=None):
        if rpm is None: rpm = self.read_register(self.engine_speed_reg)
        if rpm is None: return None
        return 8 if rpm > 100 else 0


    def device_init_late(self):
        # Additional static paths
        if '/ErrorCode' not in self.dbus:
            self.dbus.add_path('/ErrorCode', 0)
        if '/FirmwareVersion' not in self.dbus:
            self.dbus.add_path('/FirmwareVersion', None)

        is_running = None

        # Check, if status register is implemented on controller,
        # otherwise detect engine status by RPM
        status_reg_val = self.read_register(self.status_reg)
        if status_reg_val is not None:
            self.data_regs.append(self.status_reg)
            is_running = status_reg_val > 0
        else:
            log.warning('DSE status code register is not available, detecting engine status by RPM')
            self.detect_status_by_rpm = True
            engine_speed_reg_val = self.read_register(self.engine_speed_reg)
            if engine_speed_reg_val is None:
                log.error('Cannot detect engine status by RPM, as register is not available')
            else:
                status_code = self._get_status_code_from_rpm(engine_speed_reg_val)
                self.dbus.add_path(
                    '/StatusCode',
                    status_code
                )
                is_running = status_code > 0

        # Add /Start path, if GenComm System Control Functions
        # for genset telemetry start are available
        if self._check_scf_support(self.SCF_TELEMETRY_START, self.SCF_TELEMETRY_STOP):
            self.dbus.add_path(
                '/Start',
                1 if is_running else 0,
                writeable=True,
                onchangecallback=self._start_genset
            )

    def update(self):
        super(DSE_Generator, self).update()

        if self.detect_status_by_rpm and self.dbus['/StatusCode'] is not None:
            self.dbus['/StatusCode'] = self._get_status_code_from_rpm()


    def _start_genset(self, path, value):
        if value:
            self._write_scf_key(self.SCF_TELEMETRY_START)
        else:
            self._write_scf_key(self.SCF_TELEMETRY_STOP)
        return True


class DSE4xxx_Generator(DSE_Generator):

    def device_init(self):
        super(DSE4xxx_Generator, self).device_init()

        self.data_regs.append(
            Reg_DSE_alarm_old_system()
        )


models = {
    '1-4623': {
        'model':    'DSE4620/4623',
        'handler':  DSE4xxx_Generator,
    },
}


probe.add_handler(probe.ModelRegister(Reg_DSE_ident(), models,
                                      methods=['tcp'], units=[1]))
