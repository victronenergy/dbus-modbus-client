import logging
from typing import NamedTuple

log = logging.getLogger()

class NetDevSpec(NamedTuple):
    method: str
    target: str
    port: int
    unit: int = 0

    def __str__(self):
        return tostring(self)

class SerialDevSpec(NamedTuple):
    method: str
    target: str
    rate: int
    unit: int = 0

    def __str__(self):
        return tostring(self)

def tostring(d):
    return ':'.join(map(str, d))

def create(*args, **kwargs):
    #log.info('create %s %s', args, kwargs)

    method = args[0] if len(args) else kwargs.get('method', None)

    if method in ['tcp', 'udp']:
        return NetDevSpec(*args, **kwargs)

    if method in ['ascii', 'rtu']:
        return SerialDevSpec(*args, **kwargs)

    raise Exception('Bad or missing method')

def fromstring(s):
    d = s.split(':')
    d[2] = int(d[2])
    d[3] = int(d[3])

    return create(*d)

def fromstrings(ss):
    d = set()

    for s in ss:
        try:
            d.add(fromstring(s))
        except:
            continue

    return d
