# Author: Roger Blomgren <roger.blomgren@iki.fi>
# Contains essential block parsers & generators

from address import NodeAddress
from gamedata import *
from common import from_bytes, to_bytes, debug_dump
from errors import STQPacketException
from debug import debug

# STQ Block types
BLOCK_ERROR = 0
BLOCK_ACK   = 1
BLOCK_PING  = 2
BLOCK_PONG  = 3
BLOCK_SGAME = 4     # Start game
BLOCK_RGAME = 5     # Resume game
BLOCK_STARTED = 6   # Start game reply
BLOCK_JOIN  = 7     # Join supernode
BLOCK_JOINED= 8     # Join reply
BLOCK_TOPUP = 9     # Network topology update
BLOCK_VOTE  = 10
BLOCK_PUPDATE  = 11  # Player simple update
BLOCK_SUPDATE  = 12  # Supernode group update
BLOCK_NODEQRY  = 13  # Query node info
BLOCK_NODEINFO = 14  # Query reply

class STQBlock:
    """
    The STQ Block is a TLV with
    Type: 8 bits
    Length: Length of "value" field. 16 bits, big endian.
    value: 0 or more bytes
    """
    def __init__(self, blocktype, data):
        assert type(blocktype) == int
        assert type(data) == bytes

        self.blocktype = blocktype
        self.data = data

    def getType(self):
        return self.blocktype

    def generate(self):
        l = len(self.data)
        return to_bytes(self.blocktype, 1) \
        + to_bytes(l, 2) \
        + self.data

    def blocklength(self):
        """
        Returns the total length of this block, e.g. of all TLV fields.
        """
        return 3 + len(self.data)

    @staticmethod
    def parse(octets, offset):
        """
        Returs tuple (next offset, STQPacket)
        """
        if len(octets) < offset + 3:
            raise STQPacketException("Invalid TLV")
        t = from_bytes(octets[offset: offset + 1])
        offset += 1
        if t >= len(BLOCK_SELECTOR): # Is it valid?
            raise STQPacketException("Unknown block type %d" % (t,))
        l = from_bytes(octets[offset:offset + 2])
        offset += 2
        if offset + l > len(octets):
            raise STQPacketException("TLV truncated type: %d len=%d" % (t, l))
        data = octets[offset:offset + l]
        offset += l

        return (offset, BLOCK_SELECTOR[t](t, data))

ERROR_CODE_PROTERR = 0
class ErrorBlock(STQBlock):
    """
    Block data: <code:8><msg (utf-8)
    msg is optional
    """
    def __init__(self, blocktype, data):
        super().__init__(blocktype, data)
        if len(data) < 1:
            raise STQPacketException("Error block is invalid")
        # Validate message
        try:
            msg = self.getMessage()
        except UnicodeError as e:
            debug("Got error decoding error msg: %s" % (e,))
            raise STQPacketException("Invalid error message string")

    @staticmethod
    def create(code, msg):
        c = to_bytes(code, 1)
        m = msg.encode('utf-8')
        return ErrorBlock(BLOCK_ERROR, c + m)

    def getCode(self):
        return from_bytes(self.data[:1])

    def getMessage(self):
        # Strict decoding will throw in our constructor
        # after that the message is always valid
        if len(data) == 1:
            return ""
        return self.data[1:].decode('utf-8', 'strict')

class ACKBlock(STQBlock):
    """
    Block data: <ACK1><ACK2>...<ACKn>
    """
    def __init__(self, blocktype, data):
        super().__init__(blocktype, data)
        if len(data) % 4 != 0:
            raise STQPacketException("ACK block data length not a multiple of 4")
    def acks(self):
        """
        Iterate over acks
        """
        i = 0
        while i < len(self.data):
            yield from_bytes(self.data[i:i+4])
            i += 4

    def addAck(self, seq):
        self.data += to_bytes(seq, 4)

    @staticmethod
    def create():
        """
        """
        return ACKBlock(BLOCK_ACK, bytes())

class PingBlock(STQBlock):
    def __init__(self, blocktype, data):
        super().__init__(blocktype, data)

    @staticmethod
    def create(identifier):
        assert type(identifier) == bytes
        return PingBlock(BLOCK_PING, identifier)

    def __eq__(self, o):
        assert hasattr(o, "data")
        return self.data == o.data

    def __hash__(self):
        return hash(self.data)

class PongBlock(PingBlock):
    @staticmethod
    def create(ping):
        assert type(ping) == PingBlock
        return PongBlock(BLOCK_PONG, ping.data)

class SGameBlock(STQBlock):
    """
    Initial state: Node doesn't know anything, only the selected user name
    Query the server for all game info.
    - NodeStatus object with our player name (all other fields are ignored)
    - List of node addresses that we have (might be NATted)
    """
    def __init__(self, blocktype, data, verify = True):
        super().__init__(blocktype, data)

        self.address_list = []

        (offset, self.ns) = NodeStatus.parse(data, 0)
        while offset < len(self.data):
            (offset, na) = NodeAddress.parse(self.data, offset)
            self.address_list.append(na)

    def addresses(self):
        for a in self.address_list:
            yield a

    def nodeStatus(self):
        return self.ns

    @staticmethod
    def create(player_name, address_list):
        """
        Create a game start request
        """
        ns = NodeStatus(NodeSimpleStatus(bytes(16), 0, 0, 0, 0, 0), player_name)
        data = ns.generate()
        for a in address_list:
            assert type(a) == NodeAddress
            data += a.generate()

        return SGameBlock(BLOCK_SGAME, data, verify = False)

def parse_nodes(data, offset):
    """
    Parse a node list with starting list length and remaining data
    """
    count = from_bytes(data[offset: offset + 1])
    offset += 1
    nodes = []
    while count > 0:
        (offset, n) = NodeAddress.parse(data, offset)
        nodes.append(n)
        count -= 1
    return (offset, nodes)

class StartedBlock(STQBlock):
    """
    * Block data:
      - NodeAddress indicates the address that the server sees us as (e.g.
        possible NA(P)PT box address)
      - Node status: The actual game status of our ship
      - Server List: List of servers to use
      - Supers list: List of supers (if any) in our area
    """
    def __init__(self, blocktype, data, verify = True):
        """
        @verify: Used to indicate outbound packet, no verifications done
                 the packet should not be re-parsed if verify = False
        """
        super().__init__(blocktype, data)
        if not verify:
            return
        try:
            offset = 1
            (offset, self.myaddr) = NodeAddress.parse(self.data, offset)
            (offset, self.status) = NodeStatus.parse(self.data, offset)
            (offset, self.servers) = parse_nodes(self.data, offset)
            (offset, self.supers) = parse_nodes(self.data, offset)
        except IndexError as e:
            raise STQPacketException("Invalid started block")

    def code(self):
        return from_bytes(self.data[:1])

    @staticmethod
    def create(code, peer_address, status, servers, supers):
        """
        * code: Return code
        * peer_address: NodeAddress as we (server) sees it == NATted address.
        * servers: List of game servers
        * supers: List of supers in node area
        """
        assert type(code) == int
        assert type(peer_address) == NodeAddress
        assert type(status) == NodeStatus
        assert type(servers) == list
        assert type(supers) == list

        data = to_bytes(code, 1)
        data += peer_address.generate()
        data += status.generate()
        data += to_bytes(len(servers), 1)
        for n in servers:
            data += n.generate()
        data += to_bytes(len(supers), 1)
        for n in supers:
            data += n.generate()
        return StartedBlock(BLOCK_STARTED, data, verify = False)

class TopologyBlock(STQBlock):
    def __init__(self, blocktype, data, verify = True):
        super().__init__(blocktype, data)
        if not verify:
            return
        try:
            offset = 0
            slen = from_bytes(self.data[offset: offset + 1]); offset += 1
            nlen = from_bytes(self.data[offset: offset + 1]); offset += 1
            self.servers = []
            self.nodes = []
            for c in range(0, slen):
                (offset, s) = NodeAddress.parse(self.data, offset)
                self.servers.append(s)
            for c in range(0, nlen):
                (offset, n) = NodeAddress.parse(self.data, offset)
                self.nodes.append(n)
        except IndexError as e:
            raise STQPacketException("Invalid topology block")

    @staticmethod
    def create(servers, nodes):
        slen = len(servers)
        nlen = len(nodes)
        data = to_bytes(slen, 1)
        data += to_bytes(nlen, 1)
        for s in servers:
            data += s.generate()
        for n in nodes:
            data += n.generate()
        return TopologyBlock(BLOCK_TOPUP, data, verify = False)

class JoinBlock(STQBlock):
    @staticmethod
    def create():
        return JoinBlock(BLOCK_JOIN, bytes(0))

class JoinReplyBlock(STQBlock):
    def __init__(self, blocktype, data, verify = True):
        super().__init__(blocktype, data)
        if not verify:
            return
        if not len(data) == 1:
            raise STQPacketException("Invalid join reply block")

    def getCode(self):
        return from_bytes(self.data)
    @staticmethod
    def create(code):
        return JoinReplyBlock(BLOCK_JOINED, to_bytes(code, 1), verify = False)

class PlayerUpdateBlock(STQBlock):
    def __init__(self, blocktype, data, verify = True):
        super().__init__(blocktype, data)
        if verify == False:
            return
        if len(data) < 2:
            raise STQPacketException("Invalid player update block")
        offset = 2
        self.updates = []
        try:
            while offset < len(data):
                (offset, ss) = NodeSimpleStatus.parse(data, offset)
                self.updates.append(ss)
        except IndexError as e:
            raise STQPacketException("Truncated player update block")

    def getUpdates(self):
        return self.updates

    def getTick(self):
        return from_bytes(self.data[:2])

    @staticmethod
    def create(tick, updates):
        assert type(updates) == list
        data = to_bytes(tick, 2)
        for ss in updates:
            data += ss.generate()
        return PlayerUpdateBlock(BLOCK_PUPDATE, data, verify = False)

class SuperUpdateBlock(STQBlock):
    def __init__(self, blocktype, data, verify = True):
        super().__init__(blocktype, data)
        if verify == False:
            return
        if len(data) < 4:
            raise STQPacketException("Invalid super update block")
        plen = from_bytes(data[:1])
        slen = from_bytes(data[1:2])
        offset = 2
        self.peers = []
        self.supers = []
        try:
            while plen > 0:
                plen -= 1
                (offset, peer) = NodeAddress.parse(data, offset)
                self.peers.append(peer)
            while slen > 0:
                slen -= 1
                (offset, s) = NodeAddress.parse(data, offset)
                self.supers.append(s)
        except IndexError as e:
            raise STQPacketException("Truncated super update block")

    def getPeers(self):
        return self.peers

    def getSupers(self):
        return self.supers

    @staticmethod
    def create(peers, supers):
        assert type(peers) == list
        assert type(supers) == list
        plen = len(peers)
        slen = len(supers)
        data = to_bytes(plen, 1)
        data += to_bytes(slen, 1)
        for p in peers:
            assert p.valid_id()
            data += p.generate()
        for s in supers:
            assert s.valid_id()
            data += s.generate()
        return SuperUpdateBlock(BLOCK_SUPDATE, data, verify = False)


class UnimplementedBlock(STQBlock):
    def __init__(self, blocktype, data):
        raise STQPacketException("Blocktype %d unimplemented" % (blocktype,))

BLOCK_SELECTOR = [
    ErrorBlock, # 0
    ACKBlock,   # 1
    PingBlock,  # 2 Ping
    PongBlock,  # 3 Pong
    SGameBlock, # 4
    UnimplementedBlock, # 5 RGame
    StartedBlock, # 6
    JoinBlock, # 7
    JoinReplyBlock, # 8
    TopologyBlock, # 9
    UnimplementedBlock, # 10 vote
    PlayerUpdateBlock, # 11
    SuperUpdateBlock,  # 12
    ]
