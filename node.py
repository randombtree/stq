# Author: Roger Blomgren <roger.blomgren@iki.fi>
from enum import Enum
import random
from collections import deque

from twisted.internet import task
from twisted.internet import reactor
from twisted.internet.protocol import DatagramProtocol

from address import *
from blocks import *
from protocol import *
from util import *
from common import debug_dump, is_debug, monotime_ms
from debug import debug

class PeerAddress:
    def __init__(self, nodeaddress):
        assert isinstance(nodeaddress, NodeAddress)
        self.addr = nodeaddress
        self.last_sent = 0
        self.last_received = 0

    def markSent(self):
        self.last_sent = monotime_ms()
    def markRcvd(self):
        self.last_received = monotime_ms()

    def update(self, o):
        """
        Update our stats from other pa
        """
        if o.last_sent > self.last_sent:
            self.last_sent = o.last_sent
        if o.last_received > self.last_received:
            self.last_received = o.last_received

    def __hash__(self):
        # In NA we don't mind changing network addresses,
        # in PA there is a difference (since it's also used on our own ifaces)
        return self.addr.__hash__() \
            ^ hash(self.addr.address()) \
            ^ hash(self.addr.port())

    def __eq__(self, o):
        assert isinstance(o, PeerAddress)
        self.addr.__eq__(o.addr)

    def __str__(self):
        time = monotime_ms()
        last_sent = time - self.last_sent
        last_received = time - self.last_received
        if last_sent > 60000:
            last_sent = -1
        if last_received > 60000:
            last_received = -1
        return "(%d, %d)" % (last_sent, last_received) + self.addr.__str__()


class PeerState(Enum):
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    STALE = 3
    DISCONNECTING = 4
    FAILING = 5

class PeerStateListener:
    def peerStateChanged(self, peer, peerstate):
        pass

DEFAULT_PACKET_DELAY = 2
class PacketWriter:
    """
    Writes blocks to packets and sends them. Naive caller only needs
    to call addBlock to add blocks and the writer will work out the rest.
    """
    def __init__(self, peer, mss):
        self.mss = mss
        self.length = OFFSET_TLV
        self.packet = None
        self.packet_created = 0
        self.peer = peer
        self.blocks = []
        def _delayedPacketSender():
            return True

        self.timer = task.LoopingCall(_delayedPacketSender)
        self.timer_running = False

    def __enter__(self):
        pass

    def __exit__(self):
        """
        Flush out the packet
        """
        # There is enough stuff in the packet, send it away
        if self.length > 0.9 * self.mss:
            self._send()
            self._stop_timer()

    def _start_timer(self):
        def _late_send():
            self.timer_running = False
            debug("Send timer expired for %s" % (self.peer,))
            time = monotime_ms()
            if self.packet_created < time - DEFAULT_PACKET_DELAY:
                self._send()
            if self.packet:
                self._start_timer()

        if not self.timer_running:
            debug("Starting delayed timer for %s" % (self.peer,))
            self.timer_running = True
            task.deferLater(reactor, (DEFAULT_PACKET_DELAY + 1) / 1000.0, _late_send)

    def _send(self):
        # TODO: Add queuing delay (eg now - packet_created) if space available
        if self.packet:
            debug("Sending packet (%d) to %s" % (self.packet.seq, self.peer,))
            self.peer._doSend(self.packet, self.blocks)
            self.packet = None
            self.blocks = []
            self.length = OFFSET_TLV

    def _newPacket(self):
        # Get a new packet
        self.packet = self.peer.getPacket()
        self.packet_created = monotime_ms()
        self.length = OFFSET_TLV
        self._start_timer()

    def addBlock(self, block):
        """
        Adds a block for transmission. The seq number of
        the packet transmitted is returned
        """
        assert isinstance(block, STQBlock)
        if self.packet == None or block.blocklength() > self.left():
            self._send()
            self._newPacket()
        self.length += block.blocklength()
        self.blocks.append(block)
        return self.packet.seq

    def flush(self):
        if not self.packet:
            self._newPacket()

    def left(self):
        """
        The sender can try to optimize to squeeze in some data in this packet
        and then place the remainder in the next packet
        """
        return self.mss - self.length - 3 + 4 * len(self.peer.acks)

class ACKTracker:
    def __init__(self, purge_ms):
        self.purge_ms = purge_ms
        self.queue = deque()
        self.ackmap = {}
        def _purger():
            debug("Ack purge timer fired")
            time = monotime_ms()
            while len(self.queue) > 0:
                if self.queue[0][0] < time - self.purge_ms:
                    self.queue.popleft()
                else:
                    break
            if len(self.queue) == 0:
                self.purge_timer.stop()
                self.purge_timer_running = False
        self.purge_timer_running = False
        self.purge_timer = task.LoopingCall(_purger)

    def pushTracked(self, seq, acks):
        assert type(seq) == int
        assert type(acks) == list

        self.queue.append((monotime_ms(), seq))
        self.ackmap[seq] = acks
        if not self.purge_timer_running:
            self.purge_timer.start(self.purge_ms / 1000.0)
            self.purge_timer_running = True

    def popTracked(self, seq):
        if seq in self.ackmap.keys():
            return self.ackmap.pop(seq)
        # ... the purge timer will take care of the rest

class PacketListener:
    def acked(self, seq):
        pass
    def lost(self, seq):
        pass

nodecounter = 0
DEFAULT_CONNECT_TO = 3000
DEFAULT_MSS = 1200
DEFAULT_RTO = 100 # FIXME
DEFAULT_KEEPALIVE = 10000
DEFAULT_DEADTIME  = 20000
class Peer(DecayingHashListener):
    def __init__(self, peeraddr, node):
        assert type(peeraddr) == PeerAddress
        assert type(node) == STQNode

        # A little debug aid used in __str__
        global nodecounter
        self.counter = nodecounter
        nodecounter += 1

        self.node = node
        self.addr = peeraddr
        self.state = PeerState.DISCONNECTED
        self.state_listeners = []

        self.last_packet_time = 0 # When did we hear from this node last
        self.seq = round(random.random() * ((1 << 32) - 1))
        if is_debug: # Don't make my eyes cry while reading debug output
            self.seq = 0
        # TODO: rto is not synched with transmission, fix later
        self.rto = DecayingHash(DEFAULT_RTO, self)

        self.acks = []
        self.fastAck = False
        self.ackTracker = ACKTracker(3000)

        self.connect_attempts = 0

        self.packet_writer = PacketWriter(self, DEFAULT_MSS)

        def _keepalive():
            time = monotime_ms()
            if self.state == PeerState.CONNECTED:
                if self.addr.last_received < time - DEFAULT_DEADTIME:
                    debug("%s is dead?" % (self,))
                    self.setState(PeerState.STALE)
                elif self.addr.last_sent < time - DEFAULT_KEEPALIVE:
                    self.ping()
            elif self.state == PeerState.STALE:
                if self.addr.last_received < time - 2 * DEFAULT_DEADTIME:
                    debug("%s is dead!" % (self,))
                    self.setState(PeerState.DISCONNECTING)
            elif self.state == PeerState.DISCONNECTING:
                self.setState(PeerState.DISCONNECTED)
        self.keepalive = task.LoopingCall(_keepalive)
        self.keepalive.start(DEFAULT_KEEPALIVE / 1000.0)

        debug("%s created" % (self,))

    def getId(self):
        return self.addr.addr.nodeid

    def setId(self, nodeid):
        self.addr.addr.nodeid = nodeid

    def setState(self, state):
        if state == PeerState.DISCONNECTING:
            self.acks = []
        elif state == PeerState.CONNECTED:
            self.connect_attempts = 0
        oldstate = self.state
        self.state = state
        if oldstate != state:
            debug("%s changes state %s to %s" % (self, oldstate, state))
            for l in self.state_listeners:
                l.peerStateChanged(self, state)

    def addStateListener(self, listener):
        assert isinstance(listener, PeerStateListener)
        self.state_listeners.append(listener)

    def delStateListener(self, listener):
        if listener in self.state_listeners:
            self.state_listeners.remove(listener)

    # DecayingHashListener
    def itemRemoved(self, seq, listeners):
        # RTO time expired for seq, notify listeners
        for l in listeners:
           l.lost(seq)

    def nextSeq(self):
        nextSeq = self.seq
        if self.seq == (1 << 32) - 1:
            self.seq = 0
        else:
            self.seq += 1
        return nextSeq

    def connect(self):
        if not self.state in [PeerState.DISCONNECTED, PeerState.DISCONNECTING]:
            debug("Already connected to peer %s" % (self,))
            return
        debug("Connecting to %s" % (self,))
        self.connect_attempts += 1
        self.setState(PeerState.CONNECTING)
        self.ping()

    def ping(self):
        debug("Ping %s" % (self,))
        pingId = make_random_byte_blob(8)
        ping = PingBlock.create(pingId)
        self.send().addBlock(ping)

    def addAck(self, seq):
        """
        An ACK that can wait
        """
        if not seq in self.acks:
            self.acks.append(seq)

    def addFastAck(self, seq):
        """
        An ACK that must be sent NOW
        """
        self.addAck(seq)
        self.fastAck = True

    def ackTrack(self, seq):
        """
        Acks are sent until a packet has been acknowledged containing the acks
        """
        self.ackTracker.pushTracked(seq, self.acks.copy())

    def disconnect(self):
        self.state = PeerState.DISCONNECTING
        def _lateDisconnect():
            if self.state == PeerState.DISCONNECTING:
                self.state = PeerState.DISCONNECTED
        # We usually don't just disconnect so there must be a good
        # reason (e.g. failing node). Keep it away for at least this long.
        task.deferLater(reactor, 30, _lateDisconnect)

    def getPacket(self):
        """
        Get a valid packet with the right id's and stuff with ACKs added.
        Users should use send()
        """
        dialect = 0
        if self.node.role == NodeRole.SERVER:
            dialect = 1
        packet = STQPacket(self.nextSeq(), self.addr.addr.nodeid, self.node.nodeid, dialect)
        return packet

    def _doSend(self, packet, blocks):
        if self.state == PeerState.DISCONNECTING:
            return
        if len(self.acks) > 0:
            debug("Pending acks: %s" % (self.acks))
            # So, this is really innefficient - but fast to do
            # A proper impl. would try to combine the acks into ranges (e.g. create
            # an ACKRangeBlock instead when appropriate)..
            acks = ACKBlock.create()
            self.fastAck = False
            for a in self.acks:
                acks.addAck(a)
            # Track this packet for acks
            self.ackTrack(packet.seq)
            packet.addBlock(acks)
        for bl in blocks:
            packet.addBlock(bl)

        self.node.sendTo(packet, self.addr)


    def send(self):
        """
        Get a packetwriter that tracks writing and handles all the packet
        details. The packet will be sent "slightly delayed" so
        that other writers can attach stuff to it if possible
        """
        return self.packet_writer


    def trackPacket(self, seq, listener):
        """
        When the sender has added some blocks, it knows which packet
        it belongs to, now it can add a tracker that will inform when
        the packet has been ack:ed OR determined lost!
        """
        assert isinstance(listener, PacketListener)
        if seq in self.rto.keys():
           l = self.rto.get(seq)
           l.append(listener)
        else:
           self.rto.push(seq, [listener])

    def receivePacket(self, packet, host, port):
        """
        Node passes the packet to us when the node id matches
        """
        debug("%s: Received packet (%d)" % (self, packet.seq))
        self.addr.markRcvd()
        self.addAck(packet.seq)
        for block in packet.blocks:
            t = block.getType()
            name = "Unknown"
            if t < len(BLOCK_SELECTOR):
                name = BLOCK_SELECTOR[t].__name__
            debug("Got blocktype %s (%d)" % (name, t))
            if t == BLOCK_ACK:
                # We got acks
                debug("Acked: %s " % ([s for s in block.acks()],))
                for seq in block.acks():
                    # What acks where sent in that packet? Now we can remove them
                    sent_acks = self.ackTracker.popTracked(seq)
                    if sent_acks:
                        debug("%d acked: Remove acks for %s" % (seq, sent_acks,))
                        for a in sent_acks:
                            try:
                                self.acks.remove(a)
                            except ValueError:
                                pass
                    # Notify that we have a successfull ack on seq
                    callbacks = self.rto.pop(seq)
                    if callbacks:
                        for cb in callbacks:
                            cb.acked(seq)
            elif t == BLOCK_PING:
                if self.state in [PeerState.DISCONNECTED, PeerState.STALE, PeerState.CONNECTED, PeerState.CONNECTING]:
                    if valid_nodeid(self.getId()):
                        self.setState(PeerState.CONNECTED)
                        # Answer with pong
                        pong = PongBlock.create(block)
                        self.send().addBlock(pong)
                    else:
                        debug("%s Ping received while no valid id?" % (self,))
                else:
                    debug("%s: missplaced ping?" % (self,))
            elif t == BLOCK_PONG:
                if self.state == PeerState.CONNECTING:
                    debug("%s: Connect ping completed" % (self,))
                    self.setState(PeerState.CONNECTED)
            elif t == BLOCK_TOPUP:
                # Handled internally in Server
                pass
            else:
                # Maybe somebody is interested in it?
                should_ack = self.node.handleUserBlock(self, block)
                if should_ack:
                    self.addFastAck(packet.seq)
        if self.fastAck:
            self.fastAck = False
            self.flush()

    def flush(self):
        """
        Forces out packet data and appends acks
        """
        debug("%s: Flush" % (self,))
        self.packet_writer.flush()

    def __str__(self):
        return "Node (%d) %s " % (self.counter, self.state.name)+self.addr.__str__()

    def __cmp__(self, o):
        if isinstance(o, Peer):
            return self.addr == o.addr
        if isinstance(o, PeerAddress):
            return self.addr == o
        if isinstance(o, NodeAddress):
            return self.addr.addr == o


class Server(Peer):
    """
    The node representation of a server endpoint.
    Not to be mixed/confused with the server node.
    """
    def __init__(self, peeraddr, node):
        super().__init__(peeraddr, node)
        # During connecting, there _CAN_ be out of order packets. Store them
        # here, for a while
        self.queue = TimeLimitedFIFOQueue(10, 1000)
        self.connect_start = 0

    def connect(self):
        if not self.state in [PeerState.DISCONNECTED, PeerState.DISCONNECTING]:
            debug("Already connected to peer %s" % (self,))
            return
        debug("Connecting to server %s" % (self,))
        self.setState(PeerState.CONNECTING)
        self.connect_start = monotime_ms()
        self._sendConnect()

    def _sendConnect(self):
        if self.node.role == NodeRole.SERVER:
            self._sendServerConnect()
        else:
            self._sendClientConnect()

    def _sendClientConnect(self):
        # Are we doing our initial initialization?
        if not self.node.nodeid:
            # Ok, so we know basically nothing..
            rcv_id = snd_id = bytes(16)
        else:
            snd_id = self.node.nodeid
            rcv_id = self.getId()
        packet = STQPacket(self.nextSeq(), rcv_id, snd_id)
        # Simple and stupid address announce,
        # fix if used outside of course scope :)
        sg = SGameBlock.create(self.node.name, [pa.addr for pa in self.node.localAddresses()])
        packet.addBlock(sg)
        # We don't include any stale acks or other stuff
        self.node.sendTo(packet, self.addr)

    def _sendServerConnect(self):
        class ServerConnectListener(PacketListener):
            def __init__(self, peer):
                self.peer = peer
            def acked(self, seq):
                # We will receive topology update which puts us into connected state
                debug("%s: ServerConnect acked" % (self.peer,))

            def lost(self, seq):
                time = monotime_ms()
                debug("%s: ServerConnect lost: timeout %d ms" % (self.peer, time - self.peer.connect_start))
                if self.peer.connect_start < time - DEFAULT_CONNECT_TO:
                    # Timeout
                    if self.peer.state == PeerState.CONNECTING:
                        self.peer.setState(PeerState.FAILING)
                    else:
                        # Something other happened during this time?
                        pass
                else:
                    # Try again
                    self.peer._sendServerConnect()

        writer = self.send()
        servers = [s.addr.addr for s in self.node.servers.getConnectedNodes()]
        nodes = [n.addr.addr for n in self.node.nodes.getConnectedNodes()]
        tb = TopologyBlock.create(servers,
                                  nodes)
        seq = writer.addBlock(tb)
        listener = ServerConnectListener(self)
        self.trackPacket(seq, listener)

    def _serverParser(self, packet):
        """
        Pick out some server specific blocks
        """
        oldState = self.state
        if self.state != PeerState.CONNECTED:
            if not valid_nodeid(self.addr.addr.nodeid):
                self.setId(packet.snd_id)
            self.setState(PeerState.CONNECTING)
        # We are always in look for these
        topup = packet.getBlock(BLOCK_TOPUP)
        if topup:
            debug("%s: Got topology update" % (self,))
            # Peer will be re-sending these if we don't ack it fast
            self.addFastAck(packet.seq)
            for s in topup.servers:
                self.node.addServer(PeerAddress(s))
            for n in topup.nodes:
                self.node.addNode(PeerAddress(s))
            if oldState == PeerState.DISCONNECTED:
                # If we didn't initiate the connection send our stuff too
                self.connect_start = monotime_ms()
                self._sendServerConnect()

    def receivePacket(self, packet, host, port):
        """
        Node passes the packet to us when the node id matches
        """
        self.addAck(packet.seq)
        # Do server specific parsing first here
        if self.node.role == NodeRole.SERVER:
            self._serverParser(packet)
        if self.state == PeerState.CONNECTING:
            # We now got the Server nodeid, fixme: cleaner way

            self.addr.addr.nodeid = packet.snd_id
            startblock = packet.getBlock(BLOCK_STARTED)
            if startblock:
                debug("Got startblock")
                self.addFastAck(packet.seq)
                # Startblock must be the sole block when connecting
                # 1: Tell node we have a confirmed address
                pa = PeerAddress(startblock.myaddr)
                debug("My address is %s" % (pa,))
                pa.markSent() # We have clearly successfully sent via this one
                pa.markRcvd() # And we received..
                self.node.newAddress(pa)
                for s in startblock.servers:
                    debug("Got servers %s" % (startblock.servers,))
                    self.node.addServer(s)
                for s in startblock.supers:
                    debug("Got supers: %s" % (startblock.supers,))
                self.setState(PeerState.CONNECTED)
            if self.state == PeerState.CONNECTED:
                # Feed back possible out-of-order packets
                for p in self.queue.getNext():
                    super().receivePacket(packet, host, port)
                # Game engine parses this too
                super().receivePacket(packet, host, port)
                self.flush()
            else:
                # else it was an out of order packet (can't ack them as we are
                # waiting for our identity)..
                self.queue.push(packet)
        # And finally feed it through Peer for ACK parsing etc.
        super().receivePacket(packet, host, port)

    def __str__(self):
        return "Server (%d) %s " % (self.counter, self.state.name)+self.addr.__str__()



class BlockReceiver:
    def received(self, peer, block):
        """
        Returns: True - An ACK should be immediately generated (ack-eliciting)
        """
        return True

class ConnectionManager(PeerStateListener):
    def __init__(self, node, peercls, maxConnections = None):
        self.node = node
        self.peercls = peercls
        self.maxConnections = maxConnections
        self.unknownPeers = {} # Addresses to Peers without an id, typically present during init
        self.peers = {}
        self.connected = {}

    # NB: Mind the different semantics in add and getPeer.
    #     you probably want getPeer..
    def _add(self, addr):
        if addr.valid_id():
            if not addr in self.peers.keys():
                peer  = self.peercls(PeerAddress(addr), self.node)
                peer.addStateListener(self)
                debug("Creating %s" % (peer,))
                self.peers[addr] = peer
            else:
                peer = self.peers[addr]
        else:
            if not addr in self.unknownPeers.keys():
                peer = self.peercls(PeerAddress(addr), self.node)
                peer.addStateListener(self)
                debug("Creating unknown %s" % (peer,))
                self.unknownPeers[addr] = peer
            else:
                peer = self.unknownPeers[addr]
        return peer


    def getPeer(self, addr):
        if not addr in self.peers.keys():
            blank_address = NodeAddress(addr.addrinfo)
            if blank_address in self.unknownPeers.keys():
                peer = self.unknownPeers[blank_address]
                if peer.addr.addr.valid_id():
                    debug("Peer %s got an id now" % (peer,))
                    del self.unknownPeers[blank_address]
                    self.peers[peer.addr.addr] = peer
                return peer
            debug("Adding peer %s!" % (blank_address,))
            return self._add(addr)
        return self.peers[addr]

    def getConnectedNodes(self):
        l = []
        for v in self.connected.values():
            l.append(l)
        return l

    def tryConnect(self):
        # Can we connect to new nodes
        # Repeated calling might lead to more nodes connected
        # but it shouldn't matter..
        if self.maxConnections:
            canConnect = self.maxConnections - len(self.connected)
        else:
            canConnect = 10
        while not self.maxConnections or canConnect > 0:
            progress = False
            for it in [self.peers.items(), self.unknownPeers.items()]:
                for (na, peer) in it:
                    if peer.state == PeerState.DISCONNECTED:
                        peer.connect()
                        canConnect -= 1
                        progress = True
                        break
                if progress:
                    # Evaluate if we can continue
                    break
            if not progress:
                break

    def peerStateChanged(self, peer, state):
        if state == PeerState.CONNECTED:
            assert peer.addr.addr.valid_id()
            blank_address = NodeAddress(peer.addr.addr.addrinfo)
            if blank_address in self.unknownPeers:
                self.peers[peer.addr.addr] = peer
                del self.unknownPeers[blank_address]
            self.connected[peer.addr.addr] = peer
        if state == PeerState.DISCONNECTED:
            del self.connected[peer.addr.addr]
            # Try to connect to new ones
            self.tryConnect()

    def iterate(self, state):
        assert state == None or isinstance(state, PeerState)
        for p in self.peers.values():
            if not state or p.state == state:
                yield p

class NodeRole(Enum):
    NODE = 0       # Bog-standard node
    SUPER = 1      # Peer with more reponsibilities
    OLDSUPER = 2   # Retiring super
    SERVER = 3     # Server

class STQNode(PeerStateListener, DatagramProtocol):
    def __init__(self, port = 0, role = NodeRole.NODE, nodeid = None):
        assert nodeid == None or type(nodeid) == bytes
        assert nodeid == None or len(nodeid) == 16

        self.role = role         # Servers & Nodes behave mostly the same
        self.port = port         # Listen port
        self.nodeid = nodeid     # If it's 00 -> server assigns us one
        self.name = "Unknown" # UI sets this one before connecting
        self.serverList = []
        self.connectedServers = []
        self.failingServers = []
        self.connectingServers = []
        maxServerConnections = 2
        if role == NodeRole.SERVER:
            maxServerConnections = None
        self.servers = ConnectionManager(self, Server, maxServerConnections)
        self.nodes = ConnectionManager(self, Peer)

        self.receivers = {}  # Per BlockId callbacks when packets arrive

        self.started = False

        # Initial addresses
        self.newIdentity(self.nodeid)
        self.validated_address = None

        if self.nodeid == None:
            if self.role == NodeRole.SERVER:
                self.nodeid = make_random_byte_blob(16) # Should be hash of pk
            else:
                self.nodeid = bytes(16)

        for fam in [socket.AF_INET]: # TODO: IPv6
            sock = socket.socket(fam, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setblocking(False)
            # Needs some retough if enabling IPv6
            while True:
                port = self.port
                if port == 0:
                    port = round(random.random() * ((1 << 16)-1025)) + 1024
                try:
                    sock.bind(('', port))
                    break
                except OSError as e:
                    if self.port != 0:
                        raise Exception("Couldn't grab port %d" % (self.port,))
            # Let twisted handle the rest
            reactor.adoptDatagramPort(sock.fileno(), fam, self)
            # I assume twisted dups the fd
            sock.close()

    def setName(self, name):
        self.name = name

    # PeerStateListener
    def peerStateChanged(self, peer, state):
        if peer in self.connectingServers:
            if state == PeerState.CONNECTED:
                self.connectedServers.append(peer)
            elif state != PeerState.CONNECTING:
                self.failingServers.append(peer)
                self.connectingServers.remove(peer)
        # Check that we have enough servers
        self.tryConnectServer()

    def localAddresses(self):
        return [ PeerAddress(a) for a in get_my_addresses(self.port, self.nodeid) ]

    def newIdentity(self, nodeid):
        """
        Node changes identity, generally happens only after receiving
        a new nodeid from the first server we connect to
        """
        assert nodeid == None or type(nodeid) == bytes
        assert nodeid == None or len(nodeid) == 16

        self.nodeid = nodeid
        self.local_addresses = self.localAddresses()
        # Clear this also, might not be valid anyway
        self.all_addresses = self.local_addresses.copy()

    def newAddress(self, peeraddress):
        assert isinstance(peeraddress, PeerAddress)

        # Re-build our addresses and identity
        self.newIdentity(peeraddress.addr.nodeid)
        # Is it a local address?
        local = False
        for pa in self.local_addresses:
            if peeraddress == pa:
                local = True
        if not local:
            debug("NAT address %s" % (peeraddress,))
            # NAT'ed address
        self.validated_address = peeraddress.addr

    def getValidateAddress(self):
        return self.validated_address

    def validatedAddress(self, peeraddress):
        assert isinstance(nodeaddress, PeerAddress)
        if peeraddress in self.validated_addresses.keys():
            pa = self.validated_addresses[peeraddress]
            pa.update(peeraddress)

        else:
            self.validated_addresses[peeraddress] = peeraddress

    def tryConnectServer(self):
        # Nodes are connected to at most two servers, but servers
        # connect to all other servers
        debug("Trying to connect to servers..")
        self.servers.tryConnect()

    def addServer(self, server):
        assert isinstance(server, NodeAddress)
        return self.servers.getPeer(server)

    def getServers(self, state):
        return self.servers.iterate(state)

    def addNode(self, na):
        assert isinstance(na, NodeAddress)
        if self.nodeid != na.getId():
            return self.nodes.getPeer(na)
        return None

    def getNodes(self, state):
        return self.nodes.iterate(state)

    def getConnectedServers(self):
        return self.servers.getConnectedNodes()

    def start(self):
        self.started = True
        self.tryConnectServer()

    def packetReceived(self, packet, host, port):
        """
        One packet was received
        """
        dialect = packet.dialect
        # FIXME: multi protocol
        addr = NodeAddress(addrinfo(socket.AF_INET, host, port), packet.snd_id)
        if dialect == STQ_DIALECT_NODE:
            peer = self.nodes.getPeer(addr)
        elif dialect == STQ_DIALECT_SERVER:
            # Peer is a server
            peer = self.servers.getPeer(addr)
        else:
            # Send back an error paket
            debug("Invalid dialect %d" % (dialect,))
            dialect = 0
            if self.role == NodeRole.SERVER:
                dialect = 1
            p = STQPacket(0, packet.snd_id, self.nodeid, dialect)
            p.addBlock(ErrorBlock.create(ERROR_CODE_PROTERR, "Invalid dialect"))
            self.transport.write(p.generate(), host, port)
            return
        peer.receivePacket(packet, host, port)


    def datagramReceived(self, data, addr):
        host, port = addr
        debug("received from %s:%d" % (host, port))
        try:
            packet = STQPacket.parse(data)
        except STQPacketException as e:
            debug("Packet parse exception %s" % (e.__str__(),))
            debug.print_strace()
            debug_dump(data)
            # Wasn't probably a STQ packet so don't bother sending any error reports
            # (ok, we could match host and port to a connected peer and send a proper error)
            return
        self.packetReceived(packet, host, port)
        debug("<exit>")

    def sendTo(self, packet, address):
        """
        Send packet to address
        """
        assert isinstance(address, PeerAddress)
        address.markSent()
        na = address.addr
        debug("Sending to %s" % (na,))
        data = packet.generate()
        self.transport.write(data, (na.address(), na.port()))

    def registerReceiver(self, blockid, receiver):
        assert isinstance(receiver, BlockReceiver)

        if not blockid in self.receivers:
            self.receivers[blockid] = [receiver]
        else:
            self.receivers[blockid].append(receiver)

    def handleUserBlock(self, peer, block):
        """
        Peers post user blocks here and we dispatch them to the users
        (Registeded receivers)
        """
        assert isinstance(peer, Peer)

        t = block.getType()
        if t in self.receivers.keys():
            shouldAck = False
            for r in self.receivers[t]:
                ack = r.received(peer, block)
                if ack:
                    shouldAck = True
            return shouldAck
        else:
            debug("No receiver registered for blocktype %d" % (t,))
        return False


    def statusUpdate(self, status):
        assert isinstance(status, NodeStatus)
        pass

