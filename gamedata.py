# Author: Roger Blomgren <roger.blomgren@iki.fi>
from common import from_bytes, to_bytes, format_nodeid
from errors import STQPacketException

class NodeSimpleStatus:
    """
    Contains basic tick-to-tick changing values
    """
    def __init__(self, nodeid, x, y, heading, velocity, tick):
        assert tick >= 0 and tick < 1 << 16
        assert len(nodeid) == 16

        self.nodeid = nodeid
        self.x = x
        self.y = y
        self.heading = heading
        self.velocity = velocity
        self._tick = tick

    @property
    def tick(self):
        return self._tick

    @tick.setter
    def tick(self, value):
        assert type(value) == int
        assert value >= 0 and value < 1 << 16
        self._tick = tick

    def generate(self):
        # TODO: Variable-length integer encoding of x and y
        #       the QUIC variant ought to be enough for everyone
        # Save one byte by dividing the circle 360deg / 2
        assert self._tick >= 0
        heading = round(self.heading / 2)
        return self.nodeid \
            + to_bytes(self.x, 8, signed = True) \
            + to_bytes(self.y, 8, signed = True) \
            + to_bytes(heading, 1) \
            + to_bytes(self.velocity, 1) \
            + to_bytes(self._tick, 2)

    @staticmethod
    def parse(octets, offset):
        """
        returns (next offset, NSS)
        """
        assert type(octets) == bytes
        assert type(offset) == int

        nodeid = octets[offset:offset + 16]; offset += 16
        x = from_bytes(octets[offset:offset + 8], signed = True); offset += 8
        y = from_bytes(octets[offset:offset + 8], signed = True); offset += 8
        heading = from_bytes(octets[offset: offset + 1]) * 2; offset += 1
        velocity = from_bytes(octets[offset: offset + 1]); offset += 1
        tick = from_bytes(octets[offset: offset + 2]); offset += 2
        return (offset, NodeSimpleStatus(nodeid, x, y, heading, velocity, tick))

    def __str__(self):
        return "%s %d,%d %d %d %d" % (format_nodeid(self.nodeid), self.x, self.y, self.heading, self.velocity, self.tick)

    def __eq__(self, o):
        return self.nodeid == o.nodeid and \
            self.x == o.x and \
            self.y == o.y and \
            self.heading == o.heading and \
            self.velocity == o.velocity and \
            self.tick == o.tick

    
class NodeStatus:
    """
    A Full description of the node. Contains ship details etc.
    """
    def __init__(self, simplestatus, name):
        assert len(name) < 2 << 15
        self.simplestatus = simplestatus
        self.name = name

    def generate(self):
        n = self.name.encode('utf-8')
        l = to_bytes(len(n), 1)
        return self.simplestatus.generate() + l + n
    
    @staticmethod
    def parse(octets, offset):
        """
        returns (offset, NS)
        """
        (offset, ss) = NodeSimpleStatus.parse(octets, offset)
        l = from_bytes(octets[offset: offset + 1]); offset += 1
        try:
            n = octets[offset: offset + l].decode('utf-8', "strict")
            offset += l
        except UnicodeDecodeError as e:
            raise STQPacketException("Invalid node name")
        return (offset, NodeStatus(ss, n))

    def __str__(self):
        return "%s - %s" % (self.name, self.simplestatus)

    def __eq__(self, o):
        return self.name == o.name and self.simplestatus == o.simplestatus
    
