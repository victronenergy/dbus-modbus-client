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
class Shelly_Pro_Meter(device.CustomName, device.EnergyMeter):
    vendor_id = 'shelly'
    vendor_name = 'Shelly'
    min_timeout = 0.5

    # Shelly uses input registers!
    default_access = 'input'

    # Subclasses must set the following three properties!
    #   productname
    #   productmodel
    #   productid

    def device_init(self):
        self.info_regs = [
            Reg_text(0, 6, '/Serial', little=True),
        ]

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
    # Returns true if the Shelly Pro appears to run in the Monophase profile.
    #
    def monophase(self):
        try:
            self.read_register(Reg_shelly(32000))
            return True
        except Exception as err:
            self.log.info("The device appears to be in Triphase (default) mode.", err)
            return False

# Shelly Pro 3EM
#  https://www.shelly.com/products/shelly-pro-3em-x1
#
class Shelly_Pro_3EM(Shelly_Pro_Meter):
    productname = 'Shelly Pro 3EM'
    productmodel = 'SPEM-003CEBEU'
    # P120
    productid = 0x50313230

# Shelly Pro EM-50
#  https://www.shelly.com/products/shelly-pro-em-50
#
class Shelly_Pro_EM50(Shelly_Pro_Meter):
    productname = 'Shelly Pro EM-50'
    productmodel = 'SPEM-002CEBEU50'
    # P050
    productid = 0x50303530

# Shelly Pro 3EM 3CT63
#   https://www.shelly.com/products/shelly-pro-3em-3ct63
#
class Shelly_Pro_3EM_3CT63(Shelly_Pro_Meter):
    productname = 'Shelly Pro 3EM 3CT63'
    productmodel = 'SPEM-003CEBEU63'
    # P063
    productid = 0x50303633

# Shelly 3EM-63T or EM-63W Gen3
#   https://www.shelly.com/products/shelly-3em-63t-gen3
#   https://www.shelly.com/products/shelly-3em-63w-gen3
#
class Shelly_Pro_3EM_63_Gen3(Shelly_Pro_Meter):
    productname = 'Shelly 3EM-63 Gen3'
    productmodel = 'S3EM-003CXCEU63'
    # P063
    productid = 0x50303633
    
models = {
    Shelly_Pro_3EM.productmodel: {
        'model':    Shelly_Pro_3EM.productmodel,
        'handler':  Shelly_Pro_3EM,
    },
    Shelly_Pro_EM50.productmodel: {
        'model':    Shelly_Pro_EM50.productmodel,
        'handler':  Shelly_Pro_EM50,
    },
    Shelly_Pro_3EM_3CT63.productmodel: {
        'model':    Shelly_Pro_3EM_3CT63.productmodel,
        'handler':  Shelly_Pro_3EM_3CT63,
    },
    Shelly_Pro_3EM_63_Gen3.productmodel: {
        'model':    Shelly_Pro_3EM_63_Gen3.productmodel,
        'handler':  Shelly_Pro_3EM_63_Gen3,
    },
}

probe.add_handler(probe.ModelRegister(Reg_text(6, 10, 'model', little=True), models,
                                      methods=['tcp'],
                                      units=[1]))
