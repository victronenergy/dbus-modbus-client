import device
import mdns
import probe
from register import *
from victron_regs import *
import vreglink

class VE_Meter_A1B1(vreglink.VregLink, device.EnergyMeter):
    vendor_id = 've'
    vendor_name = 'Victron Energy'
    productid = 0xa1b1
    productname = 'Energy Meter VM-3P75CT'
    vreglink_base = 0x4000
    vreglink_size = 32
    role_names = ['grid', 'pvinverter', 'genset', 'acload', 'evcharger',
                  'heatpump', 'acload', 'acload']
    allowed_roles = None
    age_limit_fast = 0
    refresh_time = 20

    def add_phase_regs(self, n):
        base = 0x3040 + 8 * (n - 1)
        power = 0x3082 + 4 * (n - 1)
        self.data_regs += [
            Reg_s16( base + 0, '/Ac/L%d/Voltage' % n,        100, '%.1f V'),
            Reg_s16( base + 1, '/Ac/L%d/Current' % n,        100, '%.1f A'),
            Reg_u32b(base + 2, '/Ac/L%d/Energy/Forward' % n, 100, '%.1f kWh',
                     invalid=0xffffffff),
            Reg_u32b(base + 4, '/Ac/L%d/Energy/Reverse' % n, 100, '%.1f kWh',
                     invalid=0xffffffff),
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
            Reg_u16( 0x2001, onchange=self.pr_changed), # role
            Reg_text(0x2002, 32, '/CustomName', encoding='utf-8',
                     write=self.set_name, onchange=self.name_changed),
        ]

        phase_cfg = self.read_register(self.data_regs[0])
        phases = [phase_cfg + 1] if phase_cfg < 3 else [1, 2, 3]
        self.nr_phases = len(phases)

        role_id = self.read_register(self.data_regs[1])
        if role_id < len(self.role_names):
            self.role = self.role_names[role_id]

        self.fwver = self.read_register(self.info_regs[1])
        if self.fwver < (0, 1, 3, 1):
            self.log.info('Old firmware, data not available')
            return

        self.data_regs += [
            Reg_u16( 0x3032, '/Ac/Frequency',      100, '%.1f Hz'),
            Reg_s16( 0x3033, '/Ac/PENVoltage',     100, '%.1f V'),
            Reg_u32b(0x3034, '/Ac/Energy/Forward', 100, '%.1f kWh',
                     invalid=0xffffffff),
            Reg_u32b(0x3036, '/Ac/Energy/Reverse', 100, '%.1f kWh',
                     invalid=0xffffffff),
            Reg_u16( 0x3038, '/ErrorCode'),
            Reg_s32b(0x3080, '/Ac/Power',            1, '%.1f W'),
        ]

        for n in phases:
            self.add_phase_regs(n)

        if self.fwver < (0, 1, 5, 255):
            return

        if self.role == 'pvinverter':
            posreg = Reg_u16(0x2022, '/Position')
            self.position = self.read_register(posreg)
            self.data_regs.append(posreg)

        if self.fwver < (0, 1, 7, 0):
            return

        self.data_regs += [
            Reg_u16(0x3039, '/Ac/N/Current', 100, '%.1f A')
        ]

    def set_name(self, val):
        self.vreglink_set(0x10c, bytes(val, encoding='utf-8'))
        return True

    def name_changed(self, reg):
        self.dbus['/Devices/0/CustomName'] = reg.value

    def pr_changed(self, reg):
        self.sched_reinit()

models = {
    VE_Meter_A1B1.productid: {
        'model':    'VM-3P75CT',
        'handler':  VE_Meter_A1B1,
    },
}

probe.add_handler(probe.ModelRegister(Reg_u16(0x1000), models,
                                      methods=['udp'],
                                      units=[1]))
mdns.add_service('_victron-energy-meter._udp')
