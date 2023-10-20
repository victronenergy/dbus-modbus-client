import logging

import device
import mdns
import probe
from register import *
import shmexport
from victron_regs import *
import vreglink

log = logging.getLogger()

class VE_Meter_A1B1(shmexport.ShmExport, vreglink.VregLink, device.EnergyMeter):
    productid = 0xa1b1
    productname = 'Energy Meter VM-3P75CT'
    vreglink_base = 0x4000
    vreglink_size = 32
    allowed_roles = None
    age_limit_fast = 0
    refresh_time = 20
    shm_format = '6f'

    def phase_regs(self, n):
        base = 0x3040 + 8 * (n - 1)
        power = 0x3082 + 4 * (n - 1)
        return [
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

        ver = self.read_register(self.info_regs[1])
        if ver < (0, 1, 3, 1):
            log.info('Old firmware, data not available')
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
            self.data_regs += self.phase_regs(n)

        if ver < (0, 1, 4, 1):
            log.info('Old firmware, snapshot data not available')
            return

        self.shm_regs = [
            Reg_f16(0x3090),
            Reg_f16(0x3091),
            Reg_f16(0x3092),
            Reg_f16(0x3093),
            Reg_f16(0x3094),
            Reg_f16(0x3095),
        ]

    def set_name(self, val):
        self.vreglink_set(0x10c, bytes(val, encoding='utf-8'))
        return True

    def name_changed(self, reg):
        self.dbus['/Devices/0/CustomName'] = reg.value

    def pr_changed(self, reg):
        self.sched_reinit()

    def get_ident(self):
        return 've_%s' % self.info['/Serial']

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
