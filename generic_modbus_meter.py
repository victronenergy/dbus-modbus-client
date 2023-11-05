import struct
import device
import probe
import logging
import json
import utils

import register

class GenericMeterRTU(device.CustomName, device.EnergyMeter):
    """ Generic Meter """
    def __init__(self, config, spec, modbus, model):
        super().__init__(spec, modbus, model)
        self.config = config
        self.productid =   config.get('product_id', 0)
        self.min_timeout = config.get('timeout', 1.0)
        self.productname = config.get('product_name', "UNAMED PRODUCT");

    def init(self, dbus, enable=True):
        super().init(dbus, enable)
        self.dbus.add_path ('/Serial', self.config.get('serial', "UNKNOWN"))
        self.dbus.add_path ('/FirmwareVersion', self.config.get('version', "UNKNOWN"))

    def set_config(self, config):
        self.config = config
        return self

    def device_init(self):
        self.info_regs = []

        self.data_regs = []
        rjs = self.config['data_regs']
        for rj in rjs:
            self.data_regs.append(register.register_from_object(rj))

    def get_ident(self):
        return self.config['model']

class MatchWithConfig:
    def __init__(self, config, **args):
        self.timeout = args.get('timeout', 1)
        self.methods = args.get('methods', [])
        self.units = args.get('units', [])
        self.rates = args.get('rates', [])
        self.config = config

    def probe(self, spec, modbus, timeout=2):
        r = self.config['probe']['reg']
        reg = register.register_from_object(r)

        rr = None
        with modbus, utils.timeout(modbus, timeout or self.timeout):
            if not modbus.connect():
                raise Exception('connection error')

            if(r['type'] == 'input_register'):
                rr = modbus.read_input_registers(reg.base, reg.count, unit=spec.unit)
            elif(r['type'] == 'holding_register'):
                rr = modbus.read_holding_registers(reg.base, reg.count, unit=spec.unit)

        if rr == None or rr.isError():
            log.debug('%s: %s', modbus, rr)
            return None

        reg.decode(rr.registers)
        if(self.config['probe']['match'] == reg.value):
            return GenericMeterRTU(self.config, spec, modbus, self.config['model']).set_config(self.config)

        return None

try:
    with open(f"/data/etc/generic_rtu_meter.json") as user_file:
        file_contents = user_file.read()
        configs = json.loads(file_contents)
        for config in configs:
            probe.add_handler(MatchWithConfig(config,
                                              methods=['rtu'],
                                              units=[1],
                                              timeout=5.0))
                                              ##rates=[9600]))
except:
    raise Exception('error reading config file')
