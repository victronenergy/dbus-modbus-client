import device
import probe
from register import Reg, Reg_s16, Reg_s32b, Reg_text, Reg_mapu16, Reg_packed


class Reg_DEIF_ident(Reg_text):
    """ The DEIF controller identifies itself by an 8 char model name string,
        ASCII-encoded in four registers;
        These registers are available from firmware version 1.19.0 (May 2024)"""

    def __init__(self):
        super().__init__(770, 6, access='input')


class Reg_DEIF_status(Reg, int):

    def __init__(self):
        super().__init__(1018, 1, '/StatusCode', access='input')

    def decode(self, values):
        val = values[0]

        def decoded():
            # Bit 0: EDG bus failure / Mains failure (Single DG) / Mains failure => 10=Error
            if val & 1 << 0: return 10
            # Bit 2: DG ramp down => 9=Stopping
            if val & 1 << 2: return 9
            # Bit 6: Engine running => 8=Running
            if val & 1 << 6: return 8
            # Else: 0=Stopped
            return 0

        return self.update(
            decoded()
        )


class reg_DEIF_RemoteStartMode(Reg, int):
    """
    DEIF terminology: SEMI-AUTO
    """

    def __init__(self):
        super().__init__(1019, 1, '/RemoteStartModeEnabled')

    def decode(self, values):
        return self.update(
            1 if (values[0] & 1 << 2) else 0 # SEMI-AUTO
        )


class Reg_DEIF_unit_agonstic(Reg_s16):
    def __init__(self, us_customary_units, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.us_customary_units = us_customary_units

    def _convert(self, newval):
        return newval

    def update(self, newval):
        return super().update(
            self._convert(newval)
        )


class Reg_DEIF_temp(Reg_DEIF_unit_agonstic):
    """ Converts temperature units from Fahrenheit to Celcius, if necessary """

    def _convert(self, val):
        if self.us_customary_units:
            return (val - 32) / 1.8  # Farenheit to Celcius
        else:
            return val               # keep Celcius


class Reg_DEIF_pressure(Reg_DEIF_unit_agonstic):
    """ Converts psi or bar to kPa """

    def _convert(self, val):
        if self.us_customary_units:
            return val * 6.89476  # psi to kPa
        else:
            return val * 100      # bar to kPa


class DEIF_Tank(device.CustomName, device.Tank, device.SubDevice):
    raw_value_min = 0
    raw_value_max = 100
    raw_unit = '%'

    def __init__(self, parent, subid, register):
        self.register = register
        super().__init__(parent, subid)

    def device_init(self):
        self.data_regs = [
            Reg_s16(self.register, '/RawValue', 1, '%.0f %%', access='input'),
        ]


class DEIF_Generator(device.CustomName, device.ErrorId, device.Genset):
    vendor_id = 'deif'
    vendor_name = 'DEIF'
    productid = 0xB044
    productname = 'DEIF genset controller'
    allowed_roles = None
    default_role = 'genset'
    default_instance = 40
    min_timeout = 0.5
    default_access = 'input'
    eids_by_reg = {}

    def __init__(self, *args):
        super().__init__(*args)

        self.status_reg = Reg_DEIF_status()
        self.remote_start_mode_reg = reg_DEIF_RemoteStartMode()

    def _set_alarm_codes(self, reg):
        """ Victron-internal error id convention for DEIF:
            Start with first bit of register 1000 as eid 0,
            from there count upwards with 16 ids per register
        """
        reg_offset = reg.base - 1000
        level = 'e' if reg.base == 1057 else 'w'
        self.eids_by_reg[reg.base] = []
        for v in enumerate(reg.value):
            if v[1]:
                self.eids_by_reg[reg.base].append(
                    (level, (reg_offset * 16) + v[0])
                )

    def alarm_changed(self, reg):
        self._set_alarm_codes(reg)
        self.set_error_ids([
            x for by_reg in self.eids_by_reg.values() for x in by_reg
        ])

    def device_init(self):

        self.info_regs = [
            # /Serial -> not available
            Reg_s16(500, '/FirmwareVersion', 1),
            Reg_mapu16(5107, '/NrOfPhases', {
                0: 3, # 3 phase 3W4
                1: 3, # 3 phase 3W3
                2: 2, # 2 phase L1|L3
                3: 2, # 2 phase L1|L2
                4: 1  # 1 phase L1
            }, access='holding')
        ]      

        self.data_regs = [
            Reg_s16(504, '/Ac/L1/Voltage',      1, '%.0f V'),
            Reg_s16(505, '/Ac/L2/Voltage',      1, '%.0f V'),
            Reg_s16(506, '/Ac/L3/Voltage',      1, '%.0f V'),
            Reg_s16(513, '/Ac/L1/Current',      1, '%.0f A'),
            Reg_s16(514, '/Ac/L2/Current',      1, '%.0f A'),
            Reg_s16(515, '/Ac/L3/Current',      1, '%.0f A'),
            Reg_s16(516, '/Ac/L1/Power',   1/1000, '%.0f W'),
            Reg_s16(517, '/Ac/L2/Power',   1/1000, '%.0f W'),
            Reg_s16(518, '/Ac/L3/Power',   1/1000, '%.0f W'),
            Reg_s16(519, '/Ac/Power',      1/1000, '%.0f W'),
            Reg_s16(507, '/Ac/L1/Frequency',  100, '%.1f Hz'),
            Reg_s16(508, '/Ac/L2/Frequency',  100, '%.1f Hz'),
            Reg_s16(509, '/Ac/L3/Frequency',  100, '%.1f Hz'),
            Reg_s32b(536, '/Ac/Energy/Forward', 1, '%.0f kWh'),

            Reg_s16(593,  '/Engine/Speed',          1, '%.0f RPM', invalid=0),  # EIC
            Reg_s16(608,  '/Engine/Load',           1, '%.0f %%',  invalid=0),  # EIC
            Reg_s32b(554, '/Engine/OperatingHours', 1/3600, '%.0f s'),
            Reg_s16(566,  '/Engine/Starts',         1, '%.0f'),
            Reg_s16(567,  '/StarterVoltage',        10, '%.1f V'),

            self.status_reg,
            self.remote_start_mode_reg,

            Reg_packed(1000, 16, bits=1, items=16,
                       onchange=self.alarm_changed),
            Reg_packed(1057, 1, bits=1, items=10,
                       onchange=self.alarm_changed),
        ]

        self.name = self.read_register(
            Reg_DEIF_ident()
        )

        self._misc_device_init()

    def _misc_device_init(self):

        us_units = self.read_register(
            Reg_s16(4797, access='holding')
        ) == 1

        configs = self.read_modbus(776, 4, 'input')
        def get_reg(conf_id, fallback=None):
            """
            Value of register 776 indicates which sensor is connected 
            to Multi input 20 (register 583), 777 w.r.t. Multi Input 21 (register 584) etc.

            Value mapping:
                4 = RMI oil pressure
                5 = RMI water temperature
                6 = RMI fuel level
            """
            try: return 583 + configs.registers.index(conf_id)
            except: return fallback

        fuel_reg = get_reg(6)
        if fuel_reg:
            self.subdevices = [
                DEIF_Tank(self, 0, fuel_reg),
            ]

        # Check if oil pressure/coolant temp is configured on a analog input,
        # otherwise fall back to EIC measurement
        pres_reg = get_reg(4)
        temp_reg = get_reg(5)
        self.data_regs += [
            Reg_DEIF_pressure(
                us_units, pres_reg if pres_reg else 595, 
                '/Engine/OilPressure', 10 if pres_reg else 100, '%.0f kPa'
            ),
            Reg_DEIF_temp(
                us_units, temp_reg if temp_reg else 594, 
                '/Engine/CoolantTemperature', 1 if temp_reg else 10, '%.1f C'
            )
        ]

    def get_ident(self):
        return f"deif_{ self.name.lower() }"

    def device_init_late(self):
        super().device_init_late()

        is_running = self.read_register(self.status_reg) > 0
        self.dbus.add_path('/Start', int(is_running), writeable=True,
                           onchangecallback=self._start_genset)

        self.dbus.add_path('/EnableRemoteStartMode', 0, writeable=True,
                           onchangecallback=self._set_remote_start_mode)

        if '/ErrorCode' not in self.dbus:
            self.dbus.add_path('/ErrorCode', 0)
        if '/FirmwareVersion' not in self.dbus:
            self.dbus.add_path('/FirmwareVersion', None)

    def _start_genset(self, _, value):

        # SEMI-AUTO start
        if value: self.write_modbus(5, [(1 | 1 << 6)])  # Start + sync. (semi)
        else:     self.write_modbus(5, [(1 | 1 << 15)]) # Deload and stop (semi)

        return True

    def _set_remote_start_mode(self, _, value):
        self.write_modbus(6, [(1 | 1 << 14)]) # Semi-Auto mode
        return True


models = {
    'AGC150GEN': { # Genset unit
        'model':   'AGC 150 GEN',
        'handler': DEIF_Generator,
    },
    'AGC150DGH': { # Genset HYBRID unit
        'model':   'AGC 150 DGH',
        'handler': DEIF_Generator,
    },
    'AGC150LDG': { # Genset PMS Lite unit
        'model':   'AGC 150 LDG',
        'handler': DEIF_Generator,
    },
}

probe.add_handler(probe.ModelRegister(Reg_DEIF_ident(), models,
                                      methods=['tcp'], units=[1]))
