import struct
from utils import get_enum

AGE_LIMIT_DEFAULT = 4

AGE_LIMITS = {
    '/Ac/L1/Power': 1,
    '/Ac/L2/Power': 1,
    '/Ac/L3/Power': 1,
    '/Ac/Power':    1,
}

class Reg(object):
    def __new__(cls, *args, **kwargs):
        return super(Reg, cls).__new__(cls)

    def __init__(self, base, count, name=None, text=None, write=False):
        self.base = base
        self.count = count
        self.name = name
        self.value = None
        self.write = write
        self.time = 0
        self.max_age = AGE_LIMITS.get(name, AGE_LIMIT_DEFAULT)
        if isinstance(text, list):
            self.text = { i : text[i] for i in range(len(text)) }
        else:
            self.text = text

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return self.value == other.value
        return self.value == other

    def __float__(self):
        return float(self.value)

    def __int__(self):
        return int(self.value)

    def __str__(self):
        if isinstance(self.text, str):
            return self.text % self.value
        if isinstance(self.text, dict) and self.value in self.text:
            return self.text[self.value]
        if callable(self.text):
            return self.text(self.value)
        return str(self.value)

    def isvalid(self):
        return self.value is not None

    def update(self, newval):
        old = self.value
        self.value = newval
        return newval != old

class Reg_num(Reg, float):
    def __init__(self, base, count, name=None, scale=1, text=None, write=False):
        Reg.__init__(self, base, count, name, text, write)
        self.scale = float(scale) if scale != 1 else scale

    def set_raw_value(self, val):
        return self.update(type(self.scale)(val / self.scale))

    def decode(self, values):
        v = struct.unpack(self.coding[0], struct.pack(self.coding[1], *values))
        return self.set_raw_value(v[0])

    def encode(self):
        v = int(self.value * self.scale)
        return struct.unpack(self.coding[1], struct.pack(self.coding[0], v))

class Reg_s16(Reg_num):
    def __init__(self, base, *args, **kwargs):
        super(Reg_s16, self).__init__(base, 1, *args, **kwargs)
        self.coding = ('h', 'H')

class Reg_u16(Reg_num):
    def __init__(self, base, *args, **kwargs):
        super(Reg_u16, self).__init__(base, 1, *args, **kwargs)
        self.coding = ('H', 'H')

class Reg_s32b(Reg_num):
    def __init__(self, base, *args, **kwargs):
        super(Reg_s32b, self).__init__(base, 2, *args, **kwargs)
        self.coding = ('>i', '>2H')

class Reg_u32b(Reg_num):
    def __init__(self, base, *args, **kwargs):
        super(Reg_u32b, self).__init__(base, 2, *args, **kwargs)
        self.coding = ('>I', '>2H')

class Reg_u64b(Reg_num):
    def __init__(self, base, *args, **kwargs):
        super(Reg_u64b, self).__init__(base, 4, *args, **kwargs)
        self.coding = ('>Q', '>4H')

class Reg_s32l(Reg_num):
    def __init__(self, base, *args, **kwargs):
        super(Reg_s32l, self).__init__(base, 2, *args, **kwargs)
        self.coding = ('<i', '<2H')

class Reg_u32l(Reg_num):
    def __init__(self, base, *args, **kwargs):
        super(Reg_u32l, self).__init__(base, 2, *args, **kwargs)
        self.coding = ('<I', '<2H')

class Reg_f32l(Reg_num):
    def __init__(self, base, *args, **kwargs):
        super(Reg_f32l, self).__init__(base, 2, *args, **kwargs)
        self.coding = ('<f', '<2H')
        self.scale = float(self.scale)

class Reg_e16(Reg, int):
    def __init__(self, base, name, enum, *args, **kwargs):
        super(Reg_e16, self).__init__(base, 1, name, *args, **kwargs)
        self.enum = enum
        if self.write == True:
            self.write = [m.value for m in enum]

    def decode(self, values):
        return self.update(get_enum(self.enum, values[0]))

    def encode(self):
        return [self.value]

class Reg_text(Reg, str):
    def __init__(self, base, count, name, little=False, encoding=None, *args, **kwargs):
        super(Reg_text, self).__init__(base, count, name, *args, **kwargs)
        self.encoding = encoding or 'ascii'
        self.pfmt = '%c%dH' % (['>', '<'][little], count)

    def decode(self, values):
        newval = struct.pack(self.pfmt, *values).rstrip(b'\0')
        newval = str(newval.decode(self.encoding))
        return self.update(newval)

    def encode(self):
        return struct.unpack(self.pfmt,
            self.value.encode(self.encoding).ljust(2 * self.count, b'\0'))

class Reg_map(Reg):
    def __init__(self, base, name, tab, *args, **kwargs):
        super(Reg_map, self).__init__(base, name, *args, **kwargs)
        self.tab = tab

    def decode(self, values):
        if values[0] in self.tab:
            v = self.tab[values[0]]
        else:
            v = None
        return self.update(v)

class Reg_mapstr(Reg_map, Reg_text):
    pass

class Reg_mapu16(Reg_map, Reg_u16):
    pass
