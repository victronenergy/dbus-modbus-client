# miscellaneous utilities

import dbus
import ipaddress
import os

def private_bus():
    '''Return a private D-Bus connection

    If DBUS_SESSION_BUS_ADDRESS exists in the environment, the session
    bus is used, the system bus otherwise.
    '''

    if 'DBUS_SESSION_BUS_ADDRESS' in os.environ:
        return dbus.SessionBus(private=True)
    return dbus.SystemBus(private=True)

class timeout:
    '''Temporarily set the `timeout` attribute of an object

    To be used in a `with` statement.  Example:

      with timeout(obj, 10):
          line = obj.read()

    This calls `obj.read()` with `obj.timeout` set to 10, then
    restores the original value.

    '''

    def __init__(self, obj, timeout):
        self.obj = obj
        self.timeout = timeout

    def __enter__(self):
        self.orig_timeout = self.obj.timeout
        self.obj.timeout = self.timeout

    def __exit__(self, exc_type, exc_value, traceback):
        self.obj.timeout = self.orig_timeout

def get_networks(blacklist):
    '''Get IPv4 networks of host

    Return a list of IPv4Network objects corresponding to active
    network interfaces with a global scope address and a (possibly
    longer) list of IPv4Address objects representing the host's
    addresses on these networks.

    :param blacklist: list of interface names to ignore
    :returns: list of IPv4Network objects, IPv4Address objects

    '''

    nets = []

    try:
        with os.popen('ip -br -4 addr show scope global up') as ip:
            for line in ip:
                v = line.split()
                if v[0] in blacklist:
                    continue

                net = ipaddress.IPv4Interface(v[2])
                nets.append(net)
    except:
        pass

    addrs = [n.ip for n in nets]
    nets = list(ipaddress.collapse_addresses([n.network for n in nets]))

    return nets, addrs

def get_enum(enum, val, default=None):
    '''Get enum for value

    Return the enum matching a given value or a default.

    :param enum: the enum class
    :param val: the value to match
    :param default: default value
    :returns: enum value matching supplied value, if any, else default
    '''

    if any(val == m.value for m in enum):
        return enum(val)
    elif default != None:
        return default
    return val

def get_super(base, t):
    if not isinstance(t, type):
        t = type(t)

    return t.__mro__[t.__mro__.index(base) + 1]

def flatten(a):
    b = []

    for x in a:
        if isinstance(x, (list, tuple)):
            b += flatten(x)
        else:
            b.append(x)

    return b

def getbits(v, size):
    bit = 0

    for x in iter(v):
        if x:
            for b in range(size):
                if x & (1 << b):
                    yield bit + b

        bit += size
