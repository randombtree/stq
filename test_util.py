# Author: Roger Blomgren <roger.blomgren@iki.fi>
import pytest
from util import *
from common import *

from twisted.internet import task
from twisted.internet import reactor

def test_decayinghash():
    set_debug(True)
    timeout = False
    class _HashListener(DecayingHashListener):
        def __init__(self):
            self.items = 0
        def itemRemoved(self, key, item):
            debug("Removed: %r -> %r" % (key, item))
            self.items |= 1 << key
            if self.items == 0x15:
                reactor.stop()
    def _wakeup():
        print("Timeout!!")
        timeout = True
        reactor.stop()
    def _init(timeout):
        l = _HashListener()
        h = DecayingHash(timeout, l)
        for i in range(0, 5):
            h.push(i, True)
        return (h, l)
    (h,l) = _init(500)
    h.pop(4)
    timer = task.deferLater(reactor, 1, _wakeup)
    # NB: Reactor can only be run once, if more reactor tests are
    # needed, look into
    # https://twistedmatrix.com/documents/current/api/twisted.trial.html
    reactor.run()
    assert timeout == False
    assert l.items == 0xF

    (h, l) = _init(3000)
    values = 0
    for (k, v) in h.getNext():
        debug("Got: %r -> %r" % (k, v))
        values |= 1 << k

    assert l.items == 0
    assert values == 0x1F

