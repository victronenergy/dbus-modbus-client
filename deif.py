from itertools import chain

import device
import probe
from register import *
from utils import getbits

class Reg_DEIF_unit:
    def __init__(self, *args, conv, **kwargs):
        super().__init__(*args, **kwargs)
        self.conv = conv

    def update(self, val):
        if val is not None:
            val = self.conv(val)
        return super().update(val)

class Reg_DEIF_unit_s16(Reg_DEIF_unit, Reg_s16):
    pass

class Reg_DEIF_unit_u16(Reg_DEIF_unit, Reg_u16):
    pass

class Reg_DEIF_alarm(Reg):
    def __init__(self, base, count, *args, level, offset=0, **kwargs):
        super().__init__(base, count, *args, **kwargs)
        self.level = level
        self.offset = offset

    def error_ids(self):
        for x in getbits(self.value, 16):
            yield (self.level, self.offset + x)

class DEIF_Tank(device.CustomName, device.Tank, device.SubDevice):
    raw_value_min = 0
    raw_value_max = 100
    raw_unit = '%'

    def __init__(self, parent, subid, register):
        self.register = register
        super().__init__(parent, subid)

    def device_init(self):
        self.data_regs = [
            Reg_s16(self.register, '/RawValue', 1, '%.0f %%'),
        ]


class DEIF_Generator(device.CustomName, device.ErrorId, device.Genset):
    vendor_id = 'deif'
    vendor_name = 'DEIF'
    productid = 0xB049
    productname = 'DEIF genset controller'
    min_timeout = 0.5
    default_access = 'input'
    us_units = False

    def temperature(self, v):
        if self.us_units:
            return (v - 32) * 5 / 9
        else:
            return v

    def pressure(self, v):
        if self.us_units:
            return v * 6.89476
        else:
            return v * 100

    def alarm_changed(self, reg):
        eids = chain(self.err_reg.error_ids(), self.warn_reg.error_ids())
        self.set_error_ids(eids)

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

        self.status_reg = Reg_bit(1018, '/StatusCode', bit=6, set=8)
        self.warn_reg = Reg_DEIF_alarm(1000, 10, level='e',
                                       onchange=self.alarm_changed)
        self.err_reg  = Reg_DEIF_alarm(1057,  1, level='w', offset=57 * 16,
                                       onchange=self.alarm_changed)

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
            Reg_s16(507, '/Ac/Frequency',     100, '%.1f Hz'),
            Reg_s32b(536, '/Ac/Energy/Forward', 1, '%.0f kWh'),

            Reg_s16(593,  '/Engine/Speed',          1, '%.0f RPM', invalid=0),  # EIC
            Reg_s32b(554, '/Engine/OperatingHours', 1/3600, '%.0f s'),
            Reg_s16(566,  '/Engine/Starts',         1, '%.0f'),
            Reg_s16(567,  '/StarterVoltage',        10, '%.1f V'),
            Reg_bit(1019, '/RemoteStartModeEnabled', bit=3),

            self.status_reg,
            self.warn_reg,
            self.err_reg,
        ]

        self.us_units = self.read_register(Reg_s16(4797, access='holding')) == 1

        configs = self.read_modbus(776, 4)
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
        if fuel_reg is not None:
            self.subdevices = [
                DEIF_Tank(self, 0, fuel_reg),
            ]

        # Check if oil pressure/coolant temp is configured on a analog input,
        # otherwise fall back to EIC measurement
        pres_reg = get_reg(4)
        temp_reg = get_reg(5)
        self.data_regs += [
            Reg_DEIF_unit_s16(pres_reg or 595, '/Engine/OilPressure',
                              10 if pres_reg else 100, '%.0f kPa',
                              conv=self.pressure),
            Reg_DEIF_unit_u16(26022, '/Engine/FuelDeliveryPressure',
                              100, '%.0f kPa', invalid=0,
                              conv=self.pressure),
            Reg_DEIF_unit_s16(temp_reg or 594, '/Engine/CoolantTemperature',
                              1 if temp_reg else 10, '%.1f °C',
                              conv=self.temperature)
        ]

    def get_unique(self):
        return self.model.replace(' ', '').lower()

    def device_init_late(self):
        super().device_init_late()

        is_running = bool(self.read_register(self.status_reg))
        self.dbus.add_path('/Start', is_running, writeable=True,
                           onchangecallback=self._start_genset)

        self.dbus.add_path('/EnableRemoteStartMode', 0, writeable=True,
                           onchangecallback=self._set_remote_start_mode)

    def _start_genset(self, _, value):
        # Auto start/stop
        self.write_modbus(6, [1 | bool(value) << 11])
        return True

    def _set_remote_start_mode(self, _, value):
        if value == 1:
            self.write_modbus(6, [(1 | 1 << 13)]) # AUTO mode
        return False


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

probe.add_handler(probe.ModelRegister(Reg_text(770, 6), models,
                                      methods=['tcp', 'rtu'],
                                      rates=[115200], units=[1]))
