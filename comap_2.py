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
        super().__init__(1331, 16)

    def decode(self, values):
        v = struct.pack('>16H', *values).rstrip(b'\0')
        return self.update(v[:16].decode('ascii'))


class ComAp_Tank(device.CustomName, device.Tank, device.SubDevice):
    raw_value_min = 0
    raw_value_max = 100
    raw_unit = '%'

    def device_init(self):
        self.data_regs = [
            Reg_u16(1055, '/RawValue', 1, '%.0f %%', invalid=0x8000),
        ]

class ComAp_Generator(device.Genset):
    vendor_id = 'comap'
    vendor_name = 'ComAp'
    productid = 0xB044
    productname = 'Comap genset controller'
    min_timeout = 0.5
    reg_hole_max = 0

    def device_init(self):
        self.info_regs = [
            Reg_text(1347, 8, '/FirmwareVersion'),
            Reg_text(1331, 16, '/CustomName'),
            Reg_mapu16(1328, '/NrOfPhases', {
                0: 1, # single phase
                1: 2, 2: 2, # Split phase
                3: 3, 4: 3, 5: 3, 6: 3, 7: 3, # 3 phase
            })
        ]

        self.data_regs = [
            Reg_s16(1001, '/Ac/Power',      0.001, '%.0f W'),
            Reg_s16(1003, '/Ac/L1/Power',   0.001, '%.0f W'),
            Reg_s16(1004, '/Ac/L2/Power',   0.001, '%.0f W'),
            Reg_s16(1005, '/Ac/L3/Power',   0.001, '%.0f W'),
            Reg_s16(1006, '/Ac/Q',          0.001, '%.0f kVAr'),
            Reg_s16(1007, '/Ac/L1/Q',       0.001, '%.0f kVAr'),
            Reg_s16(1008, '/Ac/L2/Q',       0.001, '%.0f kVAr'),
            Reg_s16(1009, '/Ac/L3/Q',       0.001, '%.0f kVAr'),
            Reg_s16(1010, '/Ac/S',          0.001, '%.0f kVA'),
            Reg_s16(1011, '/Ac/L1/S',       0.001, '%.0f kVA'),
            Reg_s16(1012, '/Ac/L2/S',       0.001, '%.0f kVA'),
            Reg_s16(1013, '/Ac/L3/S',       0.001, '%.0f kVA'),
            # Reg_u16(_, '/Ac/Frequency',     10, '%.1f Hz'),
            Reg_u16(1020, '/Ac/L1/Voltage',     1, '%.0f V'),
            Reg_u16(1021, '/Ac/L2/Voltage',     1, '%.0f V'),
            Reg_u16(1022, '/Ac/L3/Voltage',     1, '%.0f V'),
            Reg_u16(1026, '/Ac/L1/Current',     1, '%.0f A'),
            Reg_u16(1027, '/Ac/L2/Current',     1, '%.0f A'),
            Reg_u16(1028, '/Ac/L3/Current',     1, '%.0f A'),
            Reg_u32b(1283, '/Ac/Energy/Forward', 1, '%.0f kWh'),

            Reg_u16(1000, '/Engine/Speed',               1, '%.0f RPM', invalid=0x8000),
            # Reg_s16(_, '/Engine/CoolantTemperature',  1, '%.1f C',   invalid=-0x8000),
            # Reg_s16(_, '/Engine/OilPressure',       0.1, '%.0f kPa', invalid=-0x8000),
            Reg_u32b(1291, '/Engine/OperatingHours', 1/360, '%.1f s', invalid=0x80000000),
            Reg_u16(1051, '/StarterVoltage',            10, '%.1f V'),

            Reg_mapu16(1325, '/StatusCode', {
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

            Reg_mapu16(1323, '/RemoteStartModeEnabled', {
                0: 0, # OFF
                1: 1, # MANUAL
                2: 0, # AUTO
                3: 0 # TEST
            })
        ]

        name = self.read_register(self.info_regs[1])
        self.name = ''.join(filter(str.isalnum, name)).lower()

        if self.read_register(Reg_u16(1055, invalid=0x8000)) is not None:
            self.subdevices = [
                ComAp_Tank(self, 0),
            ]

    def get_unique(self):
        # Use the custom name as identifier. Reasoning:
        # 1. Cannot get the serial number from modbus
        # 2. MAC address? It might be on a different subnet.
        # 3. controller's default name is "InteliLite4", which is sane enough.
        # 4. In the ComAp universe, this is already used to identify units on
        #    mobile connections, according to the manual. Page 222 of global
        #    manual.
        return self.name

    def device_init_late(self):
        super().device_init_late()

        self.dbus.add_path('/Start', 0, writeable=True,
                           onchangecallback=self._start_genset)

    def _start_genset(self, path, value):
        # As documented in the InteliGen500 G2 Global guide (2.4.0), page 286f.
        arg_reg = 4207; cmd_reg = arg_reg + 2
        if value: # Engine start
            self.write_modbus(arg_reg, [0x01FE, 0x0000]) # FC16
            self.write_modbus(cmd_reg, [0x01])           # FC06
        else: # Engine stop
            self.write_modbus(arg_reg, [0x02FD, 0x0000]) # FC16
            self.write_modbus(cmd_reg, [0x01])           # FC06


        # Get response
        res = self.read_modbus(arg_reg, 2).registers

        res_val = (res[0] << 8) | res[1]
        if res_val == 0x000001FF:
            self.log.info("Engine cmd success: Engine start")
            return True
        elif res_val == 0x000002FE:
            self.log.info("Engine cmd success: Engine stop")
            return True
        elif res_val == 0x00000001:
            self.log.warning("Engine cmd failure: Invalid argument")
        elif res_val == 0x00000002:
            self.log.warning("Engine cmd failure: Command refused ")
        else:
            self.log.error(f"Engine cmd failure, unknown response: {hex(res_val)}")

        return False

models = {
    'InteliGen500 G2-': { # InteliLite4-
        'model': 'InteliGen500 G2',
        'handler': ComAp_Generator,
    }
}
probe.add_handler(probe.ModelRegister(Reg_Comap_ident(), models,
                                      methods=['tcp'], units=[1]))
