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

        em_components = self.em_components()

        # Monophase
        if em_components < 0:
            self.init_monophase(em_components)
        
        # Triphase (default)
        else:
            self.init_triphase(em_components)

    #
    # Initializer for the Shelly Monophase profile.
    #
    def init_monophase(self, em_components):
        em_components = abs(em_components)

        if em_components > 3:
            raise Exception('Too many EM components: %d' % em_components)
        
        self.nr_phases = em_components

        self.data_regs = [
            # NOTE: We leave the 'AC Totals' blank as the monophase profile does not
            # provide us the totals.
        ]

        for n in range(em_components):
            phase = n + 1

            em_offset = n * 20
            data_offset = n * 20

            self.data_regs += [
                Reg_shelly(32003 + em_offset, '/Ac/L%d/Voltage' % phase, 1, '%.1f V'),
                Reg_shelly(32005 + em_offset, '/Ac/L%d/Current' % phase, 1, '%.1f A'),
                Reg_shelly(32310 + data_offset, '/Ac/L%d/Energy/Forward' % phase, 1000, '%.1f kWh'),
                Reg_shelly(32312 + data_offset, '/Ac/L%d/Energy/Reverse' % phase, 1000, '%.1f kWh'),
                Reg_shelly(32007 + em_offset, '/Ac/L%d/Power' % phase, 1, '%.1f W'),
                Reg_shelly(32011 + em_offset, '/Ac/L%d/PowerFactor' % phase, 1, '%.3f'),
            ]
            
    #
    # Initializer for the Shelly Triphase profile (default).
    #
    def init_triphase(self, em_components):

        self.nr_phases = 3

        #
        # This is hypothetical but the Shelly documention does mention the possibility of
        # more than one EM component in the Triphase profile. There is noting useful we
        # can do with these components other than letting the user pick the one they want
        # to show/use in the GX land.
        #
        component = 0
        if component >= em_components:
            raise Exception('EM component out of range: %d >= %d' % (component, em_components))

        em_offset = component * 80
        data_offset = component * 70

        self.data_regs = [
            Reg_shelly(31162 + data_offset, '/Ac/Energy/Forward', 1000, '%.1f kWh'),
            Reg_shelly(31164 + data_offset, '/Ac/Energy/Reverse', 1000, '%.1f kWh'),
            Reg_shelly(31013 + em_offset, '/Ac/Power', 1, '%.1f W'),
        ]
        
        for n in range(self.nr_phases):
            phase = n + 1

            phase_em_offset = em_offset + (n * 20)
            phase_data_offset = data_offset + (n * 20)

            self.data_regs += [
                Reg_shelly(31020 + phase_em_offset, '/Ac/L%d/Voltage' % phase, 1, '%.1f V'),
                Reg_shelly(31022 + phase_em_offset, '/Ac/L%d/Current' % phase, 1, '%.1f A'),
                Reg_shelly(31182 + phase_data_offset, '/Ac/L%d/Energy/Forward' % phase, 1000, '%.1f kWh'),
                Reg_shelly(31184 + phase_data_offset, '/Ac/L%d/Energy/Reverse' % phase, 1000, '%.1f kWh'),
                Reg_shelly(31024 + phase_em_offset, '/Ac/L%d/Power' % phase, 1, '%.1f W'),
                Reg_shelly(31028 + phase_em_offset, '/Ac/L%d/PowerFactor' % phase, 1, '%.3f'),
            ]

    #
    # Attepts to read the given register and returns True upon success.
    #
    def check_register(self, reg):
        try:
            self.read_register(Reg_shelly(reg))
            return True
        except Exception as err:
            self.log.info("No such Modbus register: %s", reg)
            return False
        
    #
    # Returns the number of EM components. Negative numbers imply the Shelly device 
    # is operating in the Monophase profile. Postive numbers imply the device is 
    # operating in the Triphase profile.
    #
    def em_components(self):
        # Monophase EM1:2
        if self.check_register(32040):
            return -3
        
        # Monophase EM1:1
        elif self.check_register(32020):
            return -2
        
        # Monophase EM1:0
        elif self.check_register(32000):
            return -1
        
        # Triphase EM1
        elif self.check_register(31080):
            return 2
        
        # Triphase EM0
        elif self.check_register(31000):
            return 1
        
        else:
            raise Exception("Unable to determine the number of EM components.")
            
            

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
