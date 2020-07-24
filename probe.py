import logging
import os
import struct
import threading
import time
import traceback

from pymodbus.client.sync import *
from pymodbus.register_read_message import ReadHoldingRegistersResponse
from pymodbus.utilities import computeCRC

import utils

log = logging.getLogger()

device_types = []
serial_ports = {}

class RefCount(object):
    def __init__(self, *args, **kwargs):
        super(RefCount, self).__init__(*args, **kwargs)
        self.refcount = 1

    def get(self):
        self.refcount += 1
        return self

    def put(self):
        if self.refcount > 0:
            self.refcount -= 1
        if self.refcount == 0:
            self.close()

    def close(self):
        if self.refcount == 0:
            super(RefCount, self).close()

class TcpClient(RefCount, ModbusTcpClient):
    pass

class UdpClient(RefCount, ModbusUdpClient):
    pass

class SerialClient(RefCount, ModbusSerialClient):
    def __init__(self, *args, **kwargs):
        super(SerialClient, self).__init__(*args, **kwargs)
        self.lock = threading.RLock()

    def __setattr__(self, name, value):
        super(SerialClient, self).__setattr__(name, value)
        if name == 'timeout' and self.socket:
            self.socket.timeout = value

    def put(self):
        super(SerialClient, self).put()
        if self.refcount == 0:
            del serial_ports[os.path.basename(self.port)]

    def execute(self, request=None):
        with self.lock:
            return super(SerialClient, self).execute(request)

    def __enter__(self):
        self.lock.acquire()
        return super(SerialClient, self).__enter__()

    def __exit__(self, *args):
        super(SerialClient, self).__exit__(*args)
        self.lock.release()

def make_modbus(m):
    method = m[0]

    if method == 'tcp':
        return TcpClient(m[1], int(m[2]))

    if method == 'udp':
        return UdpClient(m[1], int(m[2]))

    tty = m[1]
    rate = int(m[2])

    if tty in serial_ports:
        client = serial_ports[tty]
        if client.baudrate != rate:
            raise Exception('rate mismatch on %s' % tty)
        return client.get()

    dev = '/dev/%s' % tty
    client = SerialClient(method, port=dev, baudrate=rate)
    if not client.connect():
        client.put()
        return None

    serial_ports[tty] = client

    # send some harmless messages to the broadcast address to
    # let rate detection in devices adapt
    packet = bytes([0x00, 0x08, 0x00, 0x00, 0x55, 0x55])
    packet += struct.pack('>H', computeCRC(packet))

    for i in range(12):
        client.socket.write(packet)
        time.sleep(0.1)

    return client

def probe(mlist, pr_cb=None, pr_interval=10, timeout=None):
    num_probed = 0
    found = []

    for m in mlist:
        if isinstance(m, (str, type(u''))):
            m = m.split(':')

        if len(m) < 4:
            continue

        modbus = make_modbus(m)
        if not modbus:
            continue

        unit = int(m[-1])
        d = None

        for t in device_types:
            if t.methods and m[0] not in t.methods:
                continue

            try:
                t0 = time.time()
                d = t.probe(modbus, unit, timeout)
                t1 = time.time()
            except:
                break

            if d:
                log.info('Found %s at %s', d.model, d)
                d.method = m[0]
                d.latency = t1 - t0
                found.append(d)
                break

        modbus.put()
        num_probed += 1

        if pr_cb:
            if d or num_probed == pr_interval:
                pr_cb(num_probed, d)
                num_probed = 0

    if pr_cb and num_probed:
        pr_cb(num_probed, None)

    return found

def add_handler(devtype):
    if devtype not in device_types:
        device_types.append(devtype)

def get_attrs(attr, method):
    a = []

    for t in device_types:
        if method in t.methods:
            a += getattr(t, attr, [])

    return set(a)

def get_units(method):
    return get_attrs('units', method)

def get_rates(method):
    return get_attrs('rates', method)

class ModelRegister(object):
    def __init__(self, reg, models, **args):
        self.reg = reg
        self.models = models
        self.timeout = args.get('timeout', 1)
        self.methods = args.get('methods', [])
        self.units = args.get('units', [])
        self.rates = args.get('rates', [])

    def probe(self, modbus, unit, timeout=None):
        with modbus, utils.timeout(modbus, timeout or self.timeout):
            if not modbus.connect():
                raise Exception('connection error')
            rr = modbus.read_holding_registers(self.reg, 1, unit=unit)

        if not isinstance(rr, ReadHoldingRegistersResponse):
            log.debug('%s: %s', modbus, rr)
            return None

        v = rr.registers[0]
        if v in self.models:
            m = self.models[v]
            return m['handler'](modbus, unit, m['model'])
