import device
import probe
from register import *

# This Python script adds support for Modbus enabled Shelly devices in dbus-modbus-client version 1.58 and later.
#

# This is just a helper class to make life a bit easier with the Modbus registers.
#
class Reg_shelly(Reg_f32l):
    def __init__(self, base, name=None, scale=1, text=None, write=False, invalid=[], **kwargs):
        super().__init__(base - 30000, name, scale, text, write, invalid, **kwargs)

# Common base class for Shelly EMs but currently there's only one implementation.
#
class Shelly_Meter(device.CustomName, device.EnergyMeter):
    vendor_id = 'shelly'
    vendor_name = 'Shelly'
    min_timeout = 0.5

    # Shelly uses input registers!
    default_access = 'input'
    
    def device_init(self):
        self.info_regs = [
            Reg_text(0, 6, '/Serial', little=True),
        ]


# Shelly Pro 3EM
#   https://shelly-api-docs.shelly.cloud/gen2/Devices/Gen2/ShellyPro3EM
#
# Triphase (defualt)
#   https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM/
#   https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EMData/
#
# Monophase
#   https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM1/
#   https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM1Data/
#
# Modbus
#   https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Modbus
#
class Shelly_Pro_3EM(Shelly_Meter):
    productname = 'Shelly Pro 3EM'
    productmodel = 'SPEM-003CEBEU'

    # Shelly doesn't have a purely numerical Product ID and it's unclear what could be a good placeholder for it. 
    # Using the Base16 encoded value of 'PEM3'.
    productid = 0x50454D33

    def device_init(self):
        super().device_init()

        if self.monophase():
            # As far as I can tell there is no elegant way of mapping Shelly Pro 3EM's Monophase profile. Shelly
            # has modeled the Monophase profile as three virtual devices under the same IP:Port whereas 
            # dbus-modbus-client makes the strong assumption that an IP:Port is an unique identifier for a single
            # device. Our only option is to go truly Monophase and disregard the Phase B and C meters. *shrug*
            #
            nr_phases = 1
            
            self.data_regs += [
                Reg_shelly(32302, '/Ac/Energy/Forward', 1000, '%.1f kWh'),
                Reg_shelly(32304, '/Ac/Energy/Reverse', 1000, '%.1f kWh'),
                Reg_shelly(32007, '/Ac/Power', 1, '%.1f W'),

                Reg_shelly(32003, '/Ac/L1/Voltage', 1, '%.1f V'),
                Reg_shelly(32005, '/Ac/L1/Current', 1, '%.1f A'),
                Reg_shelly(32310, '/Ac/L1/Energy/Forward', 1000, '%.1f kWh'),
                Reg_shelly(32312, '/Ac/L1/Energy/Reverse', 1000, '%.1f kWh'),
                Reg_shelly(32007, '/Ac/L1/Power', 1, '%.1f W'),
            ]
            
        else:
            # Triphase (default)
            #
            nr_phases = 3

            self.data_regs += [
                Reg_shelly(31162, '/Ac/Energy/Forward', 1000, '%.1f kWh'),
                Reg_shelly(31164, '/Ac/Energy/Reverse', 1000, '%.1f kWh'),
                Reg_shelly(31013, '/Ac/Power', 1, '%.1f W'),

                Reg_shelly(31020, '/Ac/L1/Voltage', 1, '%.1f V'),
                Reg_shelly(31022, '/Ac/L1/Current', 1, '%.1f A'),
                Reg_shelly(31182, '/Ac/L1/Energy/Forward', 1000, '%.1f kWh'),
                Reg_shelly(31184, '/Ac/L1/Energy/Reverse', 1000, '%.1f kWh'),
                Reg_shelly(31024, '/Ac/L1/Power', 1, '%.1f W'),

                Reg_shelly(31040, '/Ac/L2/Voltage', 1, '%.1f V'),
                Reg_shelly(31042, '/Ac/L2/Current', 1, '%.1f A'),
                Reg_shelly(31202, '/Ac/L2/Energy/Forward', 1000, '%.1f kWh'),
                Reg_shelly(31204, '/Ac/L2/Energy/Reverse', 1000, '%.1f kWh'),
                Reg_shelly(31044, '/Ac/L2/Power', 1, '%.1f W'),

                Reg_shelly(31060, '/Ac/L3/Voltage', 1, '%.1f V'),
                Reg_shelly(31062, '/Ac/L3/Current', 1, '%.1f A'),
                Reg_shelly(31222, '/Ac/L3/Energy/Forward', 1000, '%.1f kWh'),
                Reg_shelly(31224, '/Ac/L3/Energy/Reverse', 1000, '%.1f kWh'),
                Reg_shelly(31064, '/Ac/L3/Power', 1, '%.1f W'),
            ]

    #
    # Returns true if the Shelly Pro 3EM appears to run in the Monophase profile.
    #
    def monophase(self):
        try:
            self.read_register(Reg_shelly(32000))
            return True
        except Exception as err:
            self.log.info("The device appears to be in Triphase (default) mode.", err)
            return False

models = {
    Shelly_Pro_3EM.productmodel: {
        'model':    Shelly_Pro_3EM.productmodel,
        'handler':  Shelly_Pro_3EM,
    },
}

probe.add_handler(probe.ModelRegister(Reg_text(6, 10, 'model', little=True), models,
                                      methods=['tcp'],
                                      units=[1]))
