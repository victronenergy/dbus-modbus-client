import os
import threading
import time

from pymodbus.client.sync import *
from pymodbus.utilities import computeCRC

class RefCount(object):
    def __init__(self, *args, **kwargs):
        super(RefCount, self).__init__(*args, **kwargs)
        self.refcount = 1
        self.in_transaction = False

    def get(self):
        self.refcount += 1
        return self

    def put(self):
        if self.refcount > 0:
            self.refcount -= 1
        if self.refcount == 0:
            self.close()

    def close(self):
        if self.refcount == 0 or self.in_transaction:
            super(RefCount, self).close()

    def execute(self, *args):
        try:
            self.in_transaction = True
            return super(RefCount, self).execute(*args)
        finally:
            self.in_transaction = False

class TcpClient(RefCount, ModbusTcpClient):
    pass

class UdpClient(RefCount, ModbusUdpClient):
    pass

class SerialClient(RefCount, ModbusSerialClient):
    def __init__(self, *args, **kwargs):
        super(SerialClient, self).__init__(*args, **kwargs)
        self.lock = threading.RLock()

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, t):
        self._timeout = t
        if self.socket:
            self.socket.timeout = t

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

serial_ports = {}

def make_client(m):
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
