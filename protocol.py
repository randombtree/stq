# Author: Roger Blomgren <roger.blomgren@iki.fi>
import socket
import random
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor

from common import monotime_ms
from common import from_bytes, to_bytes
from debug import debug

from errors import STQPacketException
from address import NodeAddress
from blocks import STQBlock

# STQ Dialects
STQ_DIALECT_NODE = 0
STQ_DIALECT_SERVER = 1
# STQ PACKET FORMAT (offsets):
OFFSET_VER = 0
OFFSET_SEQ = 1
OFFSET_RCV = OFFSET_SEQ + 4
OFFSET_DST = OFFSET_RCV + 16
OFFSET_TLV = OFFSET_DST + 16

class STQPacket:
    def __init__(self, seq, rcv_id, snd_id, dialect = 0):
        """
        * seq - Sequence number for packet.
        * rcv_id - The destination id.
        * snd_id - The sender (us) id.
        * dialect - Protocol dialect (0 for Node 1 for server)
        """
        assert type(seq) == int
        assert type(rcv_id) == bytes
        assert type(snd_id) == bytes
        assert len(rcv_id) == 16
        assert len(snd_id) == 16
        assert dialect < 8

        self.seq = seq
        self.rcv_id = rcv_id
        self.snd_id = snd_id
        self.dialect = dialect

        self.blocks = []
        self.timestamp = monotime_ms()

    def generate(self):
        # Dialect piggy-backs on the version fields
        ver = to_bytes(1 | (self.dialect << 5), 1)
        seq = to_bytes(self.seq, 4)
        data = ver + seq + self.rcv_id + self.snd_id
        for b in self.blocks:
            data += b.generate()
        return data

    def addBlock(self, block):
        self.blocks.append(block)

    def getBlock(self, blocknum):
        assert type(blocknum) == int

        for block in self.blocks:
            if block.getType() == blocknum:
                return block
        return None

    @staticmethod
    def parse(octets):
        # NB: This is really wasteful as python doesn't have
        #     read-only, zero-copy slices.
        if len(octets) < OFFSET_TLV:
            raise STQPacketException("Packet too short")
        offset = 0
        ver = from_bytes(octets[:1]); offset += 1
        dialect = (ver >> 5) & 0x7
        ver &= 0x1F
        seq = from_bytes(octets[offset: offset + 4]); offset += 4
        rcv_id = octets[offset:offset + 16]; offset += 16
        snd_id = octets[offset:offset + 16]; offset += 16
        packet = STQPacket(seq, rcv_id, snd_id, dialect)
        remaining = len(octets) - offset
        while offset < len(octets):
            (offset, block) = STQBlock.parse(octets, offset)
            packet.addBlock(block)
        return packet

    def __str__(self):
        s = "(%d) %r -> %r" % (self.seq, self.snd_id, self.rcv_id)
        for b in self.blocks:
            s += "\n\t- %d" % (b.getType())
        return s

class STQProtocolHandler(DatagramProtocol):
    """
STQ Datagram parser and data dispatcher.
    """
    def __init__(self, family, port = 0):
        self.socket = socket.socket(family = family,
                                    type = socket.SOCK_DGRAM,
                                    proto = socket.IPPROTO_UDP)
        self.socket.setblocking(False)
        random_port = False
        if port == 0:
            random_port = True
        port_ok = False
        while not port_ok:
            try:
                if random_port:
                    port = round(random.random()*((1 << 16) - 1025)) + 1024
                self.socket.bind(('', port))
                port_ok = True
            except socket.gaierror as e:
                debug("Couldn't grap port %d" % (port,))
                if not random_port:
                    raise Exception("Bind to port %d failed" % (port,))

        reactor.adoptDatagramPort(self.socket.fileno(), family, self)

    def startProtocol(self):
        debug("Starting protocol")
  
    def datagramReceived(self, data, host, port):
        debug("received from %s:%d" % (data, host, port))
        try:
            packet = STQPacket.parse(data)
            self.packetReceived(packet, host, port)
        except STQPacketException as e:
            debug("Packet parse exception" % (e.__str__(),))

    def packetReceived(self, packet, host, port):
        pass
    # Possibly invoked if there is no server listening on the
    # address to which we are sending.
    def connectionRefused(self):
        print("No one listening")      

    def send_now(self, handler, hostaddr):
        """
        Send data now to hostaddr. Handler will be called back
        with available data.
        """
        pass

    def connect(self, cb):
        pass
