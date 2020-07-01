import logging
import struct
import threading
import time
import traceback

from pymodbus.client.sync import *
from pymodbus.register_read_message import ReadHoldingRegistersResponse
from pymodbus.utilities import computeCRC

from utils import *

log = logging.getLogger()

device_types = []
serial_ports = {}

def lockable(obj):
    obj.lock = threading.Lock()
    return obj

def make_modbus(m):
    method = m[0]

    if method == 'tcp':
        return lockable(ModbusTcpClient(m[1], int(m[2])))

    if method == 'udp':
        return lockable(ModbusUdpClient(m[1], int(m[2])))

    tty = m[1]
    rate = int(m[2])

    if tty in serial_ports:
        client = serial_ports[tty]
        if client.baudrate == rate:
            return client
        client.close()

    dev = '/dev/%s' % tty
    client = lockable(ModbusSerialClient(method, port=dev, baudrate=rate))
    serial_ports[tty] = client

    # send some harmless messages to the broadcast address to
    # let rate detection in devices adapt
    packet = bytes([0x00, 0x08, 0x00, 0x00, 0x55, 0x55])
    packet += struct.pack('>H', computeCRC(packet))

    client.connect()

    for i in range(12):
        client.socket.write(packet)
        time.sleep(0.1)

    client.close()

    return client

def probe_one(devtype, modbus, unit):
    try:
        return devtype.probe(modbus, unit)
    except:
        pass

def probe(mlist, pr_cb=None, pr_interval=10):
    num_probed = 0
    found = []

    for m in mlist:
        if isinstance(m, (str, type(u''))):
            m = m.split(':')

        if len(m) < 4:
            continue

        modbus = make_modbus(m)
        unit = int(m[-1])
        d = None

        for t in device_types:
            if t.methods and m[0] not in t.methods:
                continue

            d = probe_one(t, modbus, unit)
            if d:
                log.info('Found %s at %s', d.model, d)
                d.method = m[0]
                found.append(d)
                break

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

def get_units(method):
    u = []

    for t in device_types:
        if method in t.methods and t.units:
            u += t.units

    return set(u)

class ModelRegister(object):
    def __init__(self, reg, models, timeout=0.1, methods=None, units=None):
        self.reg = reg
        self.models = models
        self.timeout = timeout
        self.methods = methods
        self.units = units

    def probe(self, modbus, unit):
        with modbus.lock:
            with timeout(modbus, self.timeout):
                rr = modbus.read_holding_registers(self.reg, 1, unit=unit)

        if not isinstance(rr, ReadHoldingRegistersResponse):
            log.debug('%s: %s', modbus, rr)
            raise Exception(rr)

        m = self.models[rr.registers[0]]
        return m['handler'](modbus, unit, m['model'])
