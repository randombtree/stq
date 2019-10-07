# Author: Roger Blomgren <roger.blomgren@iki.fi>
import socket
import pytest
from protocol import *
from blocks import *
from gamedata import *
from address import *
from conftest import NODEID, NODEID2

def test_nss_parse(simple_status):
    ss = simple_status
    assert ss.nodeid == NODEID
    assert ss.x == 2
    assert ss.y == 3
    assert ss.heading == 6
    assert ss.velocity == 10
    assert ss.tick == 4561

def test_nss_generate(simple_status):
    ss = simple_status
    data = ss.generate()
    (offset, ss2) = NodeSimpleStatus.parse(data, 0)
    assert ss2.nodeid == ss.nodeid
    assert ss2.x == ss.x
    assert ss2.y == ss.y
    assert ss2.heading == ss.heading
    assert ss2.velocity == ss.velocity
    assert ss2.tick == ss.tick
    assert ss2 == ss

def test_ns_good(node_status):
    ns = node_status
    data = ns.generate()
    (offset, ns2) = NodeStatus.parse(data, 0)
    assert ns2.simplestatus == ns.simplestatus
    assert ns2.name == 'FooBar'

def test_ns_bad(node_status):
    data = node_status.generate()
    # Tamper with data
    data = data.replace(b'Foo', b'\x80oo') # Illegal UTF-8
    with pytest.raises(STQPacketException):
        (l, ns2) = NodeStatus.parse(data, 0)


def test_na_good():
    for addr in ["127.0.0.1", "::1"]:
        na = NodeAddress(socket.getaddrinfo(addr, 666, proto = socket.IPPROTO_UDP)[0], NODEID)
        data = na.generate()
        (offset, na2) = NodeAddress.parse(data, 0)
        assert offset == len(data)
        assert na2 == na

@pytest.fixture
def packet(random_nodeid):
    def _getPacket(seq = 1, dialect = 0, rcv_id = None, snd_id = None):
        if rcv_id == None:
            rcv_id = random_nodeid()
        if snd_id == None:
            snd_id = random_nodeid()
        return STQPacket(seq, rcv_id, snd_id, dialect)
    return _getPacket

def test_na_generate_parse(packet):
    p1 = packet()
    data = p1.generate()
    p2 = STQPacket.parse(data)

    assert p1.dialect == 0
    assert p1.seq == p2.seq
    assert p1.rcv_id == p2.rcv_id
    assert p1.snd_id == p2.snd_id

    p1.dialect = 1
    p2 = STQPacket.parse(p1.generate())
    assert p2.dialect == 1

def test_na_ack(packet):
    ackblock = ACKBlock.create()
    ackblock.addAck(1)
    ackblock.addAck(2)
    found_acks = 0
    expect_acks = 1 << 1 | 1 << 2
    found_blocks = 0
    expect_blocks = 1 << ackblock.getType()
    p1 = packet()
    p1.addBlock(ackblock)
    data = p1.generate()
    p2 = STQPacket.parse(data)
    for b in p2.blocks:
        found_blocks |= 1 << b.getType()
        if type(b) == ACKBlock:
            for a in b.acks():
                found_acks |= 1 << a

    assert found_blocks == expect_blocks
    assert found_acks == expect_acks
