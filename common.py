# Author: Roger Blomgren <roger.blomgren@iki.fi>
import sys
import socket
import netifaces
import monotonic

from twisted.internet import task
from debug import debug

TICK_LENGTH = 50.0

def monotime_ms():
    return round(monotonic.time.time() * 1000)

def set_debug(b):
    debug.setDebug(b)

def is_debug():
    return debug.isDebug()


def debug_dump(buf):
    if debug.isDebug():
        num = 0
        print("------------------------", file = sys.stderr)
        for b in buf:
            end=''
            if num % 8 == 7:
                end = '\n'
            print("%02x " % (b,), file = sys.stderr, end=end)
            num += 1
        if num % 8 != 0:
            print("", file = sys.stderr)
        print("------------------------", file = sys.stderr)

def format_nodeid(nodeid):
    assert type(nodeid) == bytes
    assert len(nodeid) == 16
    return "%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x" % tuple(nodeid)

def from_bytes(data, signed = False):
    return int.from_bytes(data, byteorder = 'big', signed = signed)

def to_bytes(i, b, signed = False):
    return i.to_bytes(b, byteorder = 'big', signed = signed)

class Ticker:
    def __init__(self):
        self.setTick(0)
        def _tick_timer():
            oldtick = self.tick
            newtick = self.getTick()
            assert newtick >= 0
            if oldtick < newtick:
                self.tickHappened(newtick)
        self.timer = task.LoopingCall(_tick_timer)
        self.timer.start(TICK_LENGTH/3.0/1000.0)

    @staticmethod
    def diff(old, new):
        if new < old:
            # Tick wrap
            return (1 << 16) - old + new
        else:
            return new - old

    def tryTick(self):
        # Simple & stupid tick generator
        old_tick = self.last_tick
        time = monotime_ms()
        hops = round((time - self.last_tick) / TICK_LENGTH)
        self.tick += hops
        self.last_tick += TICK_LENGTH * hops
        while self.tick >= 1 << 16:
            self.tick -= 1 << 16
        return (old_tick, self.tick)

    def getTick(self):
        (last_tick, tick) = self.tryTick()
        return tick

    def setTick(self, tick):
        self.last_tick = monotime_ms()
        self.tick = tick

    def tickHappened(self, tick):
        pass

