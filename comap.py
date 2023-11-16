import struct
import device
import probe
from register import Reg, Reg_s16, Reg_u16, Reg_u32b, Reg_text, Reg_mapu16

class Reg_Comap_ident(Reg, str):
    """ The Comap controller returns an error if you don't read the entire 16
        registers of the identification. But we don't want to use the entire 16
        registers, we only care about the first 12 characters.  This special
        register allows us to read 16 registers, but only decode the 12
        characters we care about. """
    def __init__(self):
        super().__init__(1307, 16)

    def decode(self, values):
        v = struct.pack('>16H', *values).rstrip(b'\0')
        return self.update(v[:12].decode('ascii'))


class ComAp_Tank(device.CustomName, device.Tank, device.SubDevice):
    raw_value_min = 0
    raw_value_max = 100
    raw_unit = '%'

    def device_init(self):
        self.data_regs = [
            Reg_u16(1055, '/RawValue', 1, '%.0f %%', invalid=0x8000),
        ]

class ComAp_Generator(device.ModbusDevice):
    productid = 0xB044
    productname = 'Comap genset controller'
    allowed_roles = None
    default_role = 'genset'
    default_instance = 40
    min_timeout = 0.5

    def device_init(self):
        self.info_regs = [
            Reg_text(1323, 8, '/FirmwareVersion'),
            Reg_text(3000, 8, '/CustomName'),
            Reg_mapu16(1301, '/NrOfPhases', {
                0: 1, # single phase
                1: 2, 2: 2, # Split phase
                3: 3, 4: 3, 5: 3, 6: 3, 7: 3, # 3 phase
            })
        ]

        self.data_regs = [
            Reg_s16(1020, '/Ac/Power',      0.001, '%.0f W'),
            Reg_s16(1021, '/Ac/L1/Power',   0.001, '%.0f W'),
            Reg_s16(1022, '/Ac/L2/Power',   0.001, '%.0f W'),
            Reg_s16(1023, '/Ac/L3/Power',   0.001, '%.0f W'),
            Reg_u16(1036, '/Ac/Frequency',     10, '%.1f Hz'),
            Reg_u16(1037, '/Ac/L1/Voltage',     1, '%.0f V'),
            Reg_u16(1038, '/Ac/L2/Voltage',     1, '%.0f V'),
            Reg_u16(1039, '/Ac/L3/Voltage',     1, '%.0f V'),
            Reg_u16(1043, '/Ac/L1/Current',     1, '%.0f A'),
            Reg_u16(1044, '/Ac/L2/Current',     1, '%.0f A'),
            Reg_u16(1045, '/Ac/L3/Current',     1, '%.0f A'),
            Reg_u32b(1263, '/Ac/Energy/Forward', 1, '%.0f kWh'),

            Reg_u16(1004, '/Engine/Speed',               1, '%.0f RPM', invalid=0x8000),
            Reg_s16(1006, '/Engine/CoolantTemperature', 10, '%.1f C', invalid=-0x8000),
            Reg_s16(1008, '/Engine/OilPressure',         1, '%.0f kPa', invalid=-0x8000),
            Reg_u16(1010, '/Engine/Load',                1, '%.0f %%', invalid=0x8000),
            Reg_u32b(1013, '/Engine/OperatingHours',   1/6, '%.1f s', invalid=0x80000000),
            Reg_u16(1053, '/StarterVoltage',            10, '%.1f V'),

            Reg_mapu16(1298, '/StatusCode', {
                0: 1, # Init = Self-test
                1: 0, # Ready = Stopped
                2: 10, # Not ready = Error
                3: 2, # Prestart = Preheat
                4: 3, # Cranking = Starting
                5: 3, # Pause = Starting
                6: 3, # Starting
                7: 8, # Running
                8: 8, # Loaded (GCB is closed)
                9: 9, # Unloading, GCB is open
                10: 9, # Cooling
                11: 9, # Stop
                12: 9, # Shutdown
                13: 9, # Ventilate (for petrol engines)
                14: 10, # Emergency manual (controller does nothing)
                15: 3, # Soft loading
                16: 9, # WaitStop
                17: 9 # Another kind of venting
            }),

            Reg_mapu16(1382, '/AutoStart', {
                0: 0, # OFF
                1: 0, # MANUAL
                2: 1, # AUTO
                3: 0 # TEST
            })
        ]

        name = self.read_register(self.info_regs[1])
        self.name = ''.join(filter(str.isalnum, name)).lower()

        if self.read_register(Reg_u16(1055, invalid=0x8000)) is not None:
            self.subdevices = [
                ComAp_Tank(self, 0),
            ]

    def get_ident(self):
        # Use the custom name as identifier. Reasoning:
        # 1. Cannot get the serial number from modbus
        # 2. MAC address? It might be on a different subnet.
        # 3. controller's default name is "InteliLite4", which is sane enough.
        # 4. In the ComAp universe, this is already used to identify units on
        #    mobile connections, according to the manual. Page 222 of global
        #    manual.
        return 'comap_%s' % self.name

    def device_init_late(self):
        # Fetch the current state of the coil and populate it
        state = None
        coils = self.modbus.read_coils(4700, unit=self.unit)
        if not coils.isError():
            state = int(any(coils.bits))

        self.dbus.add_path('/Start', state, writeable=True,
                           onchangecallback=self._start_genset)
        self.dbus.add_path('/ErrorCode', 0)

    def _start_genset(self, path, value):
        # This is documented in the Comap global manual, page 204.
        # You need to write the relevant coil to stop/start the genset.
        if value:
            self.modbus.write_coil(4700, True, unit=self.unit)
        else:
            self.modbus.write_coil(4700, False, unit=self.unit)

        return True

models = {
    'InteliLite4-': { # InteliLite4-
        'model': 'ComAp InteliLite4-based genset',
        'handler': ComAp_Generator,
    }
}
probe.add_handler(probe.ModelRegister(Reg_Comap_ident(), models,
                                      methods=['tcp'], units=[1]))
