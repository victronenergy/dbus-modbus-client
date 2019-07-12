import threading
import logging
import traceback

from utils import *
import device

log = logging.getLogger()

class ScanAborted(Exception):
    pass

class Scanner(object):
    def __init__(self, port, unit, blacklist):
        self.port = port
        self.unit = unit
        self.blacklist = blacklist
        self.devices = None
        self.running = None
        self.total = None
        self.done = None

    def progress(self, n):
        if not self.running:
            raise ScanAborted()

        self.done += n

    def scan(self):
        for net in self.nets:
            log.info('Scanning %s' % net)
            hosts = net.hosts()
            mlist = [['tcp', str(h), self.port, self.unit] for h in hosts]
            self.devices += device.probe(mlist, self.progress, 4)

        log.info('Scan complete, %d device(s) found' % len(self.devices))

    def run(self):
        self.devices = []

        try:
            self.scan()
        except ScanAborted:
            log.info('Scan aborted')
        except:
            log.warn('Exception during network scan')
            traceback.print_exc()

        self.running = False

    def start(self):
        self.nets = get_networks(self.blacklist)
        if not self.nets:
            log.warn('Unable to get network addresses')
            return False

        self.total = sum([n.num_addresses - 2 for n in self.nets])
        self.done = 0
        self.running = True

        t = threading.Thread(target=self.run)
        t.daemon = True
        t.start()

        return True

    def stop(self):
        self.running = False

__all__ = ['Scanner']
