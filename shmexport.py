from multiprocessing.shared_memory import SharedMemory
import struct

SHM_VERSION = 1
SHM_HEADER = 'II'
SHM_SEQ_OFFS = 4
SHM_DATA_OFFS = 8

class ShmExport:
    shm_max_age = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shm = None
        self.shm_regs = None

    def device_init_late(self):
        super().device_init_late()

        if not self.shm_regs:
            return

        for r in self.shm_regs:
            r.max_age = self.shm_max_age

        self.data_regs.append(self.shm_regs)

        shm_size = SHM_DATA_OFFS + struct.calcsize(self.shm_format)
        self.shm = SharedMemory(create=True, size=shm_size)
        self.shm_seq = 0

        struct.pack_into(SHM_HEADER, self.shm.buf, 0,
                         SHM_VERSION, self.shm_seq)

        self.dbus.add_path('/Shm/Name', self.shm.name)
        self.dbus.add_path('/Shm/Size', shm_size)

    def destroy(self):
        super().destroy()

        if self.shm:
            self.shm.close()
            self.shm.unlink()
            self.shm = None

    def shm_seq_inc(self):
        self.shm_seq = (self.shm_seq + 1) & 0xffffffff
        struct.pack_into('I', self.shm.buf, SHM_SEQ_OFFS, self.shm_seq)

    def device_update(self):
        super().device_update()

        if not self.shm:
            return

        self.shm_seq_inc()
        struct.pack_into(self.shm_format, self.shm.buf, SHM_DATA_OFFS,
                         *[r.value for r in self.shm_regs])
        self.shm_seq_inc()
