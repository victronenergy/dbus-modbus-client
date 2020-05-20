import threading
import logging
import traceback

from utils import *
import device

log = logging.getLogger()

MODBUS_UNIT_MIN = 1
MODBUS_UNIT_MAX = 247

class ScanAborted(Exception):
    pass

class Scanner(object):
    def __init__(self):
        self.devices = None
        self.running = None
        self.total = None
        self.done = None

    def progress(self, n):
        if not self.running:
            raise ScanAborted()

        self.done += n

    def run(self):
        self.devices = []

        try:
            self.scan()
            log.info('Scan complete, %d device(s) found', len(self.devices))
        except ScanAborted:
            log.info('Scan aborted')
        except:
            log.warn('Exception during bus scan')
            traceback.print_exc()

        self.running = False

    def start(self):
        self.done = 0
        self.running = True

        t = threading.Thread(target=self.run)
        t.daemon = True
        t.start()

        return True

    def stop(self):
        self.running = False

class NetScanner(Scanner):
    def __init__(self, proto, port, unit, blacklist):
        Scanner.__init__(self)
        self.proto = proto
        self.port = port
        self.unit = unit
        self.blacklist = blacklist

    def scan(self):
        for net in self.nets:
            log.info('Scanning %s', net)
            hosts = net.hosts()
            mlist = [[self.proto, str(h), self.port, self.unit] for h in hosts]
            self.devices += device.probe(mlist, self.progress, 4)

    def start(self):
        self.nets = get_networks(self.blacklist)
        if not self.nets:
            log.warn('Unable to get network addresses')
            return False

        self.total = sum([n.num_addresses - 2 for n in self.nets])

        return Scanner.start(self)

class SerialScanner(Scanner):
    def __init__(self, tty, rate, mode):
        Scanner.__init__(self)
        self.tty = tty
        self.rate = rate
        self.mode = mode

    def scan_units(self, units):
        mlist = [[self.mode, self.tty, self.rate, u] for u in units]
        self.devices += device.probe(mlist, self.progress, 4)

    def scan(self):
        log.info('Scanning %s (quick)', self.tty)
        units = device.get_units(self.mode)
        self.scan_units(units)

        log.info('Scanning %s (full)', self.tty)
        units = range(MODBUS_UNIT_MIN, MODBUS_UNIT_MAX + 1)
        self.scan_units(units)

    def start(self):
        self.total = MODBUS_UNIT_MAX
        return Scanner.start(self)

__all__ = ['NetScanner', 'SerialScanner']
