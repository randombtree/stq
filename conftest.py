# Author: Roger Blomgren <roger.blomgren@iki.fi>
import pytest
import random
from gamedata import *
from address import *

from util import make_random_byte_blob

NODEID =  b'\x00\x00\x00\x00\x00\x00\x00\x00\x07\x06\x05\x04\x03\x02\x01N'
NODEID2 = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00M'

@pytest.fixture
def random_nodeid():
    def _make_nodeid():
        return make_random_byte_blob(16)
    return _make_nodeid

@pytest.fixture
def simple_status():
    assert len(NODEID) == 16
    p = NODEID \
        + b'\x00\x00\x00\x00\x00\x00\x00\x02' \
        + b'\x00\x00\x00\x00\x00\x00\x00\x03' \
        + b'\x03' \
        + b'\x0a' \
        + b'\x11\xd1' # Tick 4561
    (offset, ss) = NodeSimpleStatus.parse(p, 0)
    assert offset == len(p)
    return ss

@pytest.fixture
def node_status(simple_status):
    return NodeStatus(simple_status, 'FooBar')

@pytest.fixture
def node_address():
    return NodeAddress(socket.getaddrinfo("127.0.0.1", 666, proto = socket.IPPROTO_UDP)[0], NODEID)

@pytest.fixture
def random_address(random_nodeid):
    def _addressfunc():
        nodeid = random_nodeid()
        binaddr = make_random_byte_blob(4)
        addr = socket.inet_ntop(socket.AF_INET, binaddr)
        ai = addrinfo(socket.AF_INET, addr, round(random.random() * ((1 << 16) -1)))
        return NodeAddress(ai, nodeid)
    return _addressfunc
