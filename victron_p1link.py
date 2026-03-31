from device import EnergyMeter
import mdns
import probe
from register import *
from victron_regs import *
from vreglink import VregLink

class VE_Meter_P1Link(VregLink, EnergyMeter):
    vendor_id = 've'
    vendor_name = 'Victron Energy'
    productid = 0xc02f
    productname = 'P1Link'

    vreglink_base = 0x4000
    vreglink_size = 32
    allowed_roles = None
    default_role = 'grid'
    refresh_time = 1000

    def get_phases(self, cfg):
        if cfg == 0:
            return [1]
        if cfg == 3:
            return [1, 2, 3]
        self.log.warning('Unknown phase configuration, using 3-phase')
        return [1, 2, 3]

    def add_phase_regs(self, n):
        base = 0x3040 + 8 * (n - 1)
        current = 0x3058 + 2 * (n - 1)
        power = 0x3082 + 4 * (n - 1)
        self.data_regs += [
            Reg_s16( base + 0, '/Ac/L%d/Voltage' % n,        100, '%.1f V'),
            Reg_s32b(current,  '/Ac/L%d/Current' % n, 100, '%.1f A'),
            Reg_s32b(power,    '/Ac/L%d/Power' % n,            1, '%.1f W'),
        ]

    def device_init(self):
        self.info_regs = [
            Reg_text( 0x1001, 8, '/Serial'),
            VEReg_ver(0x1009, '/FirmwareVersion'),
            Reg_u16(  0x100b, '/HardwareVersion'),
            Reg_text( 0x2002, 32, '/CustomName', encoding='utf-8'),
        ]

        self.data_regs = [
            Reg_u16( 0x2000, onchange=self.pr_changed), # phase config
            Reg_text(0x2002, 32, '/CustomName', encoding='utf-8',
                     write=self.set_name, onchange=self.name_changed),
            Reg_u32b(0x3034, '/Ac/Energy/Forward', 100, '%.1f kWh',
                     invalid=0xffffffff),
            Reg_u32b(0x3036, '/Ac/Energy/Reverse', 100, '%.1f kWh',
                     invalid=0xffffffff),
            Reg_s32b(0x3080, '/Ac/Power',            1, '%.1f W'),
        ]

        phases = self.get_phases(self.read_register(self.data_regs[0]))
        self.nr_phases = len(phases)
        for n in phases:
            self.add_phase_regs(n)

    def set_name(self, val):
        self.vreglink_set(0x10c, bytes(val, encoding='utf-8'))
        return True

    def name_changed(self, reg):
        self.dbus['/Devices/0/CustomName'] = reg.value

    def pr_changed(self, reg):
        self.sched_reinit()

models = {
    VE_Meter_P1Link.productid: {
        'model':    'P1Link rev A',
        'handler':  VE_Meter_P1Link,
    },
}

probe.add_handler(probe.ModelRegister(Reg_u16(0x1000), models,
                                      methods=['udp'],
                                      units=[1]))
mdns.add_service('_victron-p1link._udp')
