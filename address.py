# Author: Roger Blomgren <roger.blomgren@iki.fi>
import socket
import netifaces

from common import from_bytes, to_bytes
from errors import STQPacketException
from util import *

def get_my_addresses(port, nodeid):
    for i in netifaces.interfaces():
        for (fam, listing) in netifaces.ifaddresses(i).items():
            if fam == socket.AF_INET or fam == socket.AF_INET6:
                for info in listing:
                    yield NodeAddress(addrinfo(fam, info['addr'], port), nodeid)


def addrinfo(fam, addr, port):
    # So netifaces does something weird and corrupts the link local IPv6 address, fixup!
    # (appends the ifname there)
    assert type(addr) == str
    assert type(port) == int
    if fam == socket.AF_INET6:
        if addr.startswith("fe80::"):
            clean = addr.split("%")
            addr = clean[0]
    return (fam, socket.IPPROTO_UDP, 17, '', (addr, port, 0, 0))

class NodeAddress:
    """
    Describes a node address, ip-address, port and node id
    """
    def __init__(self, addrinfo, nodeid = None):
        assert type(nodeid) == bytes or nodeid == None
        assert nodeid == None or len(nodeid) == 16
        assert type(addrinfo) == tuple

        if nodeid == None:
            nodeid = bytes(16)
        self.addrinfo = addrinfo
        self.nodeid = nodeid

        family = self.family()
        assert family in [socket.AF_INET, socket.AF_INET6]


    def generate(self):
        """
        Generate network data representation
        """

        f = self.family()
        a = socket.inet_pton(f, self.address())
        f = to_bytes(f, 1)
        p = to_bytes(self.port(), 2)

        data = to_bytes(self.family(), 1)
        data += a
        data += to_bytes(self.port(), 2)
        data += self.nodeid
        return data

    @staticmethod
    def parse(octets, offset):
        try:
            family = from_bytes(octets[offset:offset + 1])
            offset += 1
            if family == socket.AF_INET:
                l = 4
            elif family == socket.AF_INET6:
                l = 16
            else:
                raise STQPacketException("Bad Node address: family = %d" % (family,))
            addr = socket.inet_ntop(family, octets[offset:offset + l])
            offset += l
            port = from_bytes(octets[offset: offset + 2])
            offset += 2
            nodeid = octets[offset: offset + 16]
            offset += 16
            # A bit lazy, but at least correct:
            addrinfo = socket.getaddrinfo(addr, port, proto = socket.IPPROTO_UDP)[0]
            return (offset, NodeAddress(addrinfo, nodeid))
        except IndexError as e:
            raise STQPacketException("Invalid node address")

    def setId(self, nodeid):
        assert type(nodeid) == bytes
        assert len(nodeid) == 16
        self.nodeid = nodeid
    def getId(self):
        return self.nodeid
    def family(self):
        return int(self.addrinfo[0])

    def address(self):
        return self.addrinfo[4][0]

    def port(self):
        return self.addrinfo[4][1]

    def len(self):
        """ Return the serialized length """
        l = 1 + 2 + 16
        if family == socket.AF_INET:
            l += 4
        else:
            l += 16
        return l

    def valid_id(self):
        return valid_nodeid(self.nodeid)

    def __str__(self):
        return "(%d) %s : %d" % (self.family(), self.address(), self.port())

    def __eq__(self, o):
        # We primarily match by nodeid, else we try with the address
        # address matches happen in early connections when most of
        # the topology is unknown
        if valid_nodeid(self.nodeid) and valid_nodeid(o.nodeid):
            return self.nodeid == o.nodeid
        else:
            return self.addrinfo[0] == o.addrinfo[0] and \
                self.addrinfo[4][0] == o.addrinfo[4][0] and \
                self.addrinfo[4][1] == o.addrinfo[4][1]

    def __hash__(self):
        if self.valid_id():
            return hash(self.nodeid)
        return hash(self.addrinfo[0]) ^ hash(self.addrinfo[4][0]) ^ hash(self.addrinfo[4][1])
