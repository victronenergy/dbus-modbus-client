import threading
import logging
import time
import traceback

from utils import *
import device
import probe

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
        self.lock = threading.Lock()
        self.num_found = 0

    def progress(self, n, dev):
        if not self.running:
            raise ScanAborted()

        self.done += n

        if dev:
            self.num_found += 1
            with self.lock:
                self.devices.append(dev)

    def run(self):
        self.devices = []

        try:
            self.scan()
            log.info('Scan complete')
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
    def __init__(self, proto, port, unit, blacklist, timeout=0.25):
        Scanner.__init__(self)
        self.proto = proto
        self.port = port
        self.unit = unit
        self.blacklist = blacklist
        self.timeout = timeout

    def scan(self):
        for net in self.nets:
            log.info('Scanning %s', net)
            hosts = filter(net.ip.__ne__, net.network.hosts())
            mlist = [[self.proto, str(h), self.port, self.unit] for h in hosts]
            probe.probe(mlist, self.progress, 4, timeout=self.timeout)

    def start(self):
        self.nets = get_networks(self.blacklist)
        if not self.nets:
            log.warn('Unable to get network addresses')
            return False

        self.total = sum([n.network.num_addresses - 3 for n in self.nets])

        return Scanner.start(self)

class SerialScanner(Scanner):
    def __init__(self, tty, rates, mode, timeout=0.1, full=False):
        Scanner.__init__(self)
        self.tty = tty
        self.rates = rates
        self.mode = mode
        self.timeout = timeout
        self.full = full

    def progress(self, n, dev):
        super(SerialScanner, self).progress(n, dev)
        if self.num_found:
            time.sleep(1)

    def scan_units(self, units, rate):
        mlist = [[self.mode, self.tty, rate, u] for u in units]
        return probe.probe(mlist, self.progress, 1, timeout=self.timeout)

    def scan(self):
        units = probe.get_units(self.mode)
        rates = self.rates or probe.get_rates(self.mode)

        for r in rates:
            log.info('Scanning %s @ %d bps (quick)', self.tty, r)
            found = self.scan_units(units, r)
            if found:
                rates = [r]
                break

        if not self.full:
            return

        units = set(range(MODBUS_UNIT_MIN, MODBUS_UNIT_MAX + 1)) - \
            set(d.unit for d in found)

        for r in rates:
            log.info('Scanning %s @ %d bps (full)', self.tty, r)
            self.scan_units(units, r)

    def start(self):
        self.total = MODBUS_UNIT_MAX
        return Scanner.start(self)

__all__ = ['NetScanner', 'SerialScanner']
