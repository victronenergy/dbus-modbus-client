import struct

class Reg(object):
    def __init__(self, base, count, name):
        self.base = base
        self.count = count
        self.name = name
        self.value = None

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return self.value == other.value
        return False

    def __float__(self):
        return float(self.value)

    def __int__(self):
        return int(self.value)

    def __str__(self):
        return str(self.value)

    def isvalid(self):
        return self.value is not None

    def update(self, newval):
        old = self.value
        self.value = newval
        return newval != old

class Reg_num(Reg, float):
    def __new__(cls, *args):
        return float.__new__(cls)

    def __init__(self, base, count, name, scale=1, fmt=None):
        Reg.__init__(self, base, count, name)
        self.scale = float(scale)
        self.fmt = fmt

    def __str__(self):
        if self.fmt:
            return self.fmt % self.value
        return str(self.value)

    def set_raw_value(self, val):
        return self.update(val / self.scale)

class Reg_uint16(Reg_num):
    def decode(self, values):
        if values[0] == 0x7ffff:
            return self.update(None)

        return self.set_raw_value(values[0])

class Reg_int32(Reg_num):
    def decode(self, values):
        if values[1] == 0x7ffff:
            return self.update(None)

        v = struct.unpack('<i', struct.pack('<2H', *values))[0]
        return self.set_raw_value(v)

class Reg_text(Reg, str):
    def __new__(cls, *args):
        return str.__new__(cls)

    def decode(self, values):
        newval = struct.pack('>%dH' % len(values), *values).rstrip('\0')
        return self.update(newval)

class Reg_map(Reg):
    def __init__(self, base, count, name, tab):
        Reg.__init__(self, base, count, name)
        self.tab = tab

    def decode(self, values):
        if values[0] in self.tab:
            v = self.tab[values[0]]
        else:
            v = None
        return self.update(v)

class Reg_mapstr(Reg_map, Reg_text):
    pass
