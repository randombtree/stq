# Author: Roger Blomgren <roger.blomgren@iki.fi>
from address import *
from blocks import *
from debug import debug
from common import debug_dump

def test_pingpong(random_nodeid):
    nodeid = random_nodeid()
    ping = PingBlock.create(nodeid)
    data = ping.generate()
    (offset, ping2) = STQBlock.parse(data, 0)
    assert type(ping2) == PingBlock
    assert offset == len(data)
    assert ping2 == ping

    pong = PongBlock.create(ping2)
    assert pong == ping2
    data = pong.generate()
    (offset, pong2) = STQBlock.parse(data, 0)
    assert type(pong2) == PongBlock
    assert pong2 == pong
    assert pong2 == ping2

def test_started_block(node_status, node_address, random_address):
    debug.setDebug(True)
    servers = [ random_address() for c in range(0,10)]
    supers = [ random_address() for c in range(0,10)]
    sb = StartedBlock.create(0, node_address, node_status, servers, supers)
    data = sb.generate()
    debug_dump(data)
    (offset, sb2) = STQBlock.parse(data, 0)

    assert offset == len(data)
    assert sb2.myaddr == node_address
    assert sb2.status == node_status
    assert len(sb2.servers) == len(servers)
    assert len(sb2.supers) == len(supers)

    for srv in sb2.servers:
        servers.remove(srv)
    for sup in sb2.supers:
        supers.remove(sup)

    assert len(servers) == 0
    assert len(supers) == 0


def test_sgame_block():
    addresses = [ a for a in get_my_addresses(1024, bytes(16))]

    assert len(addresses) > 0
    sg = SGameBlock.create("FooBar", addresses)
    data = sg.generate()
    (offset, sg2) = SGameBlock.parse(data, 0)
    assert offset == len(data)

    for a in sg2.addresses():
        print(a)
        addresses.remove(a)

    assert len(addresses) == 0

def test_topology_block(random_address):
    servers = [ random_address() for c in range(0,10)]
    nodes = [ random_address() for c in range(0,10)]
    block = TopologyBlock.create(servers, nodes)
    data = block.generate()
    (offset, block2) = STQBlock.parse(data, 0)
    assert offset == len(data)

    assert len(block2.servers) == len(servers)
    for s in block2.servers:
        assert s in servers
        servers.remove(s)
        print(s)
    assert len(servers) == 0

    assert len(block2.nodes) == len(nodes)
    for n in block2.nodes:
        assert n in nodes
        nodes.remove(n)
    assert len(nodes) == 0

def test_su_block(random_address):
    peers = [ random_address() for c in range(0,10)]
    supers = [ random_address() for c in range(0, 10)]
    block = SuperUpdateBlock.create(peers, supers)
    data = block.generate()
    (offset, block2) = STQBlock.parse(data, 0)
    assert offset == len(data)
    for peer in block2.peers:
        assert peer in peers
        peers.remove(peer)
    assert len(peers) == 0
    for peer in block2.supers:
        assert peer in supers
        supers.remove(peer)
    assert len(supers) == 0
