from itertools import chain
import queue
import threading
import logging
import time
import traceback

from utils import *
import device
import devspec
import probe

log = logging.getLogger()

MODBUS_UNIT_MIN = 1
MODBUS_UNIT_MAX = 247

class ScanAborted(Exception):
    pass

class Scanner:
    def __init__(self):
        self.devices = []
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
        try:
            t0 = time.time()
            self.scan()
            t1 = time.time()
        except ScanAborted:
            pass
        except:
            log.warning('Exception during bus scan')
            traceback.print_exc()

        if self.running:
            log.info('Scan completed in %d seconds', t1 - t0)
        else:
            log.info('Scan aborted')

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

    def get_devices(self):
        with self.lock:
            d = self.devices
            self.devices = []
            return d

class NetScanner(Scanner):
    def __init__(self, port, blacklist, timeout=0.25):
        super().__init__()
        self.protos = ['tcp', 'udp']
        self.port = port
        self.blacklist = blacklist
        self.timeout = timeout

    def do_probe(self):
        while True:
            host = self.hosts.get()
            if not host or not self.running:
                break

            m = [devspec.create(p, str(host), self.port) for p in self.protos]

            try:
                probe.probe(m, self.progress, timeout=self.timeout)
            except:
                pass

            self.hosts.task_done()

    def scan(self):
        self.hosts = queue.Queue(maxsize=8)
        tasks = []

        log.info('Scanning %s', ', '.join(map(str, self.nets)))

        for i in range(8):
            t = threading.Thread(target=self.do_probe)
            t.start()
            tasks.append(t)

        for h in chain(*map(lambda n: n.hosts(), self.nets)):
            if not self.running:
                break

            if h in self.addrs:
                continue

            self.hosts.put(h)

        if self.running:
            self.hosts.join()

        for t in tasks:
            if not self.hosts.full():
                self.hosts.put(None)

        for t in tasks:
            t.join()

        self.hosts = None

    def start(self):
        self.nets, self.addrs = get_networks(self.blacklist)
        if not self.nets:
            log.warning('Unable to get network addresses')
            return False

        num_hosts = sum([n.num_addresses - 2 for n in self.nets])
        num_hosts -= len(self.addrs)
        self.total = len(self.protos) * num_hosts

        return super().start()

class SerialScanner(Scanner):
    def __init__(self, tty, rates, mode, timeout=0.1, full=False):
        super().__init__()
        self.tty = tty
        self.rates = rates
        self.mode = mode
        self.timeout = timeout
        self.full = full

    def progress(self, n, dev):
        super().progress(n, dev)
        if self.num_found:
            time.sleep(1)

    def scan_units(self, units, rate):
        mlist = [devspec.create(self.mode, self.tty, rate, u) for u in units]
        d = probe.probe(mlist, self.progress, 1, timeout=self.timeout)
        return d[0]

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
        return super().start()

__all__ = ['NetScanner', 'SerialScanner']
