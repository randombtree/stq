# Author: Roger Blomgren <roger.blomgren@iki.fi>
import random
from collections import deque

from twisted.internet import task
from twisted.internet import reactor

from common import monotime_ms
from debug import debug

def make_random_byte_blob(count):
    a = bytearray(count)
    for i in range(0,count):
        a[i] =  round(random.random() *255)
    return bytes(a)

def make_nodeid():
    return make_random_byte_blob(16)

def valid_nodeid(nodeid):
    if len(nodeid) != 16:
        return False
    for i in range(0, 16):
        if nodeid[i] != 0:
            return True

class TimeLimitedFIFOQueue:
    def __init__(self, max_size, timeout_ms):
        self.timeout_ms = timeout_ms
        self.queue=deque(maxlen = max_size)

        def _fifoPurger():
            time = monotime_ms()
            while len(self.queue) > 0:
                if self.queue[0][0] < (time - self.timeout_ms):
                    self._pop()
                else:
                    break
            if len(self.queue) == 0:
                self.timer.stop()
                self.timer_running = False
        self.timer = task.LoopingCall(_fifoPurger)
        self.timer_running = False

    def _setTimeout(self):
        if len(self.queue) > 0 and not self.timer_running:
            self.timer_running = True
            self.timer.start(self.timeout_ms / 1000.0)

    def push(self, item):
        self.queue.append((monotime_ms(), item))
        self._setTimeout()

    def _pop(self):
        """
        Impl. specific detail: Allow DecayingHash to overload this
        for its own handling
        """
        if len(self.queue) > 0:
            (t, i) = self.queue.popleft()
            return i
        return None

    def pop(self):
        return self._pop()

    def getNext(self):
        while len(self.queue) > 0:
            yield self._pop()

class DecayingHashListener:
    def itemRemoved(self, key, item):
        pass

class DecayingHash(TimeLimitedFIFOQueue):
    """
    Hash table thar removes entries after a timeout
    """
    def __init__(self, timeout_ms, listener):
        assert isinstance(listener, DecayingHashListener)
        super().__init__(None, timeout_ms)
        self.listener = listener
        self.dictionary = {}

    def push(self, key, value):
        super().push(key)
        self.dictionary[key] = value

    def _pop(self):
        key = super()._pop()
        if type(key) != None and key in self.dictionary.keys():
            value = self.dictionary.pop(key)
            if self.listener:
                self.listener.itemRemoved(key, value)
            return (key, value)

        return None

    def pop(self, key):
        if key in self.dictionary.keys():
            return self.dictionary.pop(key)
        return None

    def getNext(self):
        while len(self.queue) > 0:
            key = super()._pop()
            if key in self.dictionary.keys():
                value = self.dictionary.pop(key)
                yield (key, value)
            else:
                continue

    def get(self, key):
        if key in self.dictionary.keys():
            return self.dictionary[key]
        return None

    def keys(self):
        return self.dictionary.keys()
