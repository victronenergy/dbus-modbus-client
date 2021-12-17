import faulthandler
import logging
import os
import threading
import time

log = logging.getLogger()

class Watchdog(object):
    def __init__(self, timeout=30):
        self.time = None
        self.timeout = timeout

    def update(self):
        self.time = time.time()

    def run(self):
        while True:
            if time.time() - self.time > self.timeout:
                log.error('Watchdog timeout')
                faulthandler.dump_traceback()
                os._exit(1)

            time.sleep(self.timeout)

    def start(self):
        self.update()
        t = threading.Thread(target=self.run)
        t.daemon = True
        t.start()
