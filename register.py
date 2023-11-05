import struct
from utils import get_enum
from collections.abc import Iterable

class Reg:
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, base, count, name=None, text=None, write=False,
                 max_age=None, onchange=None):
        self.base = base
        self.count = count
        self.name = name
        self.value = None
        self.write = write
        self.onchange = onchange
        self.time = 0
        self.max_age = max_age
        self.text = text
        self.base_register_type = 4

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
        if hasattr(self.text, '__getitem__'):
            try:
                return self.text[self.value]
            except:
                pass
        if callable(self.text):
            return self.text(self.value)
        return str(self.value)

    def as_input_register(self):
        self.base_register_type = 3
        return self

    def isvalid(self):
        return self.value is not None

    def update(self, newval):
        old = self.value
        self.value = newval
        changed = newval != old
        if self.onchange and changed:
            self.onchange(self)
        return changed

class Reg_num(Reg, float):
    rtype = int

    def __init__(self, base, name=None, scale=1, text=None, write=False, invalid=[], **kwargs):
        super().__init__(base, self.count, name, text, write, **kwargs)
        self.scale = float(scale) if scale != 1 else self.rtype(scale)
        self.invalid = list(invalid) if isinstance(invalid, Iterable) else [invalid]

    def set_raw_value(self, val):
        return self.update(type(self.scale)(val / self.scale))

    def decode(self, values):
        v = struct.unpack(self.coding[0], struct.pack(self.coding[1], *values))
        if v[0] in self.invalid:
            return self.update(None)
        return self.set_raw_value(v[0])

    def encode(self):
        v = self.rtype(self.value * self.scale)
        return struct.unpack(self.coding[1], struct.pack(self.coding[0], v))

class Reg_s16(Reg_num):
    coding = ('h', 'H')
    count = 1

class Reg_u16(Reg_num):
    coding = ('H', 'H')
    count = 1

class Reg_s32b(Reg_num):
    coding = ('>i', '>2H')
    count = 2

class Reg_u32b(Reg_num):
    coding = ('>I', '>2H')
    count = 2

class Reg_u64b(Reg_num):
    coding = ('>Q', '>4H')
    count = 4

class Reg_s32l(Reg_num):
    coding = ('<i', '<2H')
    count = 2

class Reg_u32l(Reg_num):
    coding = ('<I', '<2H')
    count = 2

class Reg_f32l(Reg_num):
    coding = ('<f', '<2H')
    count = 2
    rtype = float

class Reg_f32b(Reg_num):
    coding = ('>f', '>2H')
    count = 2
    rtype = float

class Reg_e16(Reg, int):
    def __init__(self, base, name, enum, **kwargs):
        super().__init__(base, 1, name, **kwargs)
        self.enum = enum
        if self.write == True:
            self.write = [m.value for m in enum]

    def decode(self, values):
        return self.update(get_enum(self.enum, values[0]))

    def encode(self):
        return [self.value]

class Reg_text(Reg, str):
    def __init__(self, base, count, name=None, little=False, encoding=None, **kwargs):
        super().__init__(base, count, name, **kwargs)
        self.encoding = encoding or 'ascii'
        self.pfmt = '%c%dH' % (['>', '<'][little], count)

    def decode(self, values):
        newval = struct.pack(self.pfmt, *values).rstrip(b'\0')
        newval = str(newval.decode(self.encoding))
        return self.update(newval)

    def encode(self):
        return struct.unpack(self.pfmt,
            self.value.encode(self.encoding).ljust(2 * self.count, b'\0'))

class Reg_map:
    def __init__(self, base, name, tab, *args, **kwargs):
        super().__init__(base, name, *args, **kwargs)
        self.tab = tab

    def decode(self, values):
        if values[0] in self.tab:
            v = self.tab[values[0]]
        else:
            v = None
        return self.update(v)

class Reg_mapu16(Reg_map, Reg_u16):
    pass


def register_from_object(obj):
    try:
        ref = None
        if obj['data_type'] == 's16':
            ref = Reg_s16
        elif obj['data_type'] == 'u16 ':
            ref = Reg_u16
        elif obj['data_type'] == 's32b':
            ref = Reg_s32b
        elif obj['data_type'] == 'u32b':
            ref = Reg_u32b
        elif obj['data_type'] == 'u64b':
            ref = Reg_u64b
        elif obj['data_type'] == 's32l':
            ref = Reg_s32l
        elif obj['data_type'] == 'u32l':
            ref = Reg_u32l
        elif obj['data_type'] == 'f32l':
            ref = Reg_f32l
        elif obj['data_type'] == 'f32b':
            ref = Reg_f32b
        elif obj['data_type'] == 'e16':
            ref = Reg_e16
        elif obj['data_type'] == 'text':
            ref = Reg_text
        elif obj['data_type'] == 'mapu16':
            ref = Reg_mapu16


        base =  obj.get('base', None)
        name  = obj.get('name', None)
        text  = obj.get('text', None)
        write = obj.get('write', False)
        extra = obj.get('extra', {})
        reg_type  = obj.get('type', 'holding_register')

        ret = None
        if issubclass(ref, Reg_num):
            scale =   obj.get('scale', 1)
            invalid = obj.get('invalid', [])
            ret = ref(base, name, scale, text, write, invalid, *extra)
        elif issubclass(ref, Reg_e16):
            enum = obj.get('enum', {})
            ret = ref(base, name, enum, *extra)
        elif issubclass(ref, Reg_text):
            count = obj.get('count', 1)
            little = obj.get('little', False)
            encoding = obj.get('encoding', None)
            ret = ref(base, name, count, name, little, encoding, *extra)
        elif issubclass(ref, Reg_map):
            args = obj.get('extra', {})
            tab = obj.get('tab', {})
            ret = ref(base, name, tab, args, *extra)

        if reg_type == 'input_register':
            ret.as_input_register();

        return ret
    except:
        return None
