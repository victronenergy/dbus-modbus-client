from register import *

class VEReg_ver(Reg, int):
    def __init__(self, base, name):
        super().__init__(base, 2, name)

    def __int__(self):
        v = self.value
        return v[1] << 16 | v[2] << 8 | v[3]

    def __str__(self):
        if self.value[3] == 0xFF:
            return 'v%x.%02x' % self.value[1:3]
        return 'v%x.%02x-beta-%02x' % self.value[1:4]

    def decode(self, values):
        return self.update(struct.unpack('4B', struct.pack('>2H', *values)))
