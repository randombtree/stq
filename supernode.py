# Author: Roger Blomgren <roger.blomgren@iki.fi>
from gamedata import *
from node import *

class StatusChangeListener:
    def statusChanged(self, simpleStatus):
        pass

class UpdateQueue:
    def __init__(self, peer):
        self.peer = peer
        self.updates = {}

    def addUpdate(self, status):
        # Don't queue status back
        if status.nodeid == self.peer.getId():
            return
        if status.nodeid in self.updates.keys():
            oldstatus = self.updates[status.nodeid]
            if oldstatus.tick < status.tick or abs(oldstatus.tick - status.tick) > 1000:
                self.updates[status.nodeid] = status
        self.updates[status.nodeid] = status

    def getUpdates(self):
        values = [ v for v in self.updates.values()]
        self.updates.clear()
        return values

class SuperNode(BlockReceiver, PeerStateListener):
    def __init__(self, node, forcedSuper = False, supers = []):
        self.node = node
        self.supers = {} # Peers that are supernodes
        self.peers = {}
        self.listeners = []
        self.updateQueue = {}
        self.gameStates = {}
        self.forcedSuper = forcedSuper
        self.isSuper = False
        self.lastTick = 0
        if self.forcedSuper:
            self.isSuper = True
        self.node.registerReceiver(BLOCK_JOIN, self)
        self.node.registerReceiver(BLOCK_JOINED, self)
        self.node.registerReceiver(BLOCK_PUPDATE, self)
        self.node.registerReceiver(BLOCK_SUPDATE, self)
        if len(supers) > 0:
            for sup in supers:
                peer = self.node.addNode(sup)
                if peer:
                    peer.addStateListener(self)
                    self.supers[peer.getId()] = peer

    @property
    def isSuper(self):
        return self._isSuper

    @isSuper.setter
    def isSuper(self, value):
        assert type(value) == bool
        debug("super: %s" % value)
        self._isSuper = value

    def getSupers(self):
        return [peer.addr.addr for peer in self.supers.values()]

    def createUpdateQueue(self, peer):
        """ Create an updatequeue for peer """
        assert isinstance(peer, Peer)
        nid = peer.getId()
        if not nid in self.updateQueue:
            q = UpdateQueue(peer)
            # Send all updates we have avail next tick
            for s in self.gameStates.values():
                q.addUpdate(s)
            self.updateQueue[nid] = q

    def kickPeer(self, peer):
        nid = peer.getId()
        if nid in self.supers:
            del self.supers[nid]
        if nid in self.peers:
            del self.peers[nid]
        if nid in self.updateQueue:
            del self.updateQueue[nid]
        peer.disconnect()
        self.parent.maybeConnectSupers()

    def joinSuper(self, peer):
        join = JoinBlock.create()
        class WaitJoinACK(PacketListener):
            def __init__(self, parent):
                self.parent = parent
                self.started = monotime_ms()
            def acked(self, seq):
                debug("Join acked")
                # Atill a JoinReply must come
                # TODO: Timer for it
            def lost(self, seq):
                if self.started < monotime_ms() - 3000:
                    debug("Super %s is being difficult" % peer)
                    self.parent.kickPeer(peer)
                else:
                    _send_join(self)
        def _send_join(l):
            seq = peer.send().addBlock(join)
            peer.trackPacket(seq, l)
        _send_join(WaitJoinACK(self))

    def ackJoin(self, peer, code):
        reply = JoinReplyBlock.create(code)
        class WaitACK(PacketListener):
            def __init__(self, parent):
                self.parent = parent
                self.started = monotime_ms()
            def acked(self, seq):
                debug("%s is now part of our supernode" % (peer,))
            def lost(self, seq):
                if self.started < monotime_ms() - 3000:
                    debug("%s Timeout on join reply. Kick it" % (peer,))
                    self.parent.kickPeer(peer)
                else:
                    _do_send(self)
        def _do_send(l):
            seq = peer.send().addBlock(reply)
            peer.trackPacket(seq, l)
        _do_send(WaitACK(self))

    def sendSuperUpdate(self):
        if not self.isSuper:
            return
        if not self.node.validated_address:
            debug("No validated address yet?")
            return
        supers = self.getSupers()
        supers.append(self.node.validated_address)
        peers = []
        su = SuperUpdateBlock.create([], supers)
        for sup in self.supers.values():
            sup.send().addBlock(su)
        for server in self.node.getServers(PeerState.CONNECTED):
            server.send().addBlock(su)

    def received(self, peer, block):
        nid = peer.getId()
        t = block.getType()
        if t == BLOCK_JOIN:
            debug("Got join request from %s" % peer)
            if self.isSuper:
                self.ackJoin(peer, 0)
                # IF the join fails, tese will be purged:
                self.peers[nid] = peer
                self.createUpdateQueue(peer)
                peer.addStateListener(self)
            else:
                debug("We are not a super, please back off")
                self.ackJoin(peer, 1)
        elif t == BLOCK_JOINED:
            if block.getCode() == 0:
                debug("Successfully joined super %s" % (peer,))
                self.supers[nid] = peer
                self.createUpdateQueue(peer)
            else:
                debug("Super %s buffed us" % (peer,))
                del self.supers[nid]
                self.maybeConnectSupers()
        elif t == BLOCK_SUPDATE:
            debug("super update")
            # We get all the peers and supers
            updated = False # Did anything change in the super topology?
            for p in block.peers:
                nid = p.getId()
                if not nid in self.peers.keys():
                    peer = self.node.addNode(p)
                    self.peers[nid] = peer
            for s in block.supers:
                nid = s.getId()
                if not nid in self.supers.keys():
                    peer = self.node.addNode(s)
                    if peer:
                        debug("New supernode %s" % peer)
                        peer.addStateListener(self)
                        self.supers[nid] = peer
                        peer.connect()
                        updated = True
            if updated:
                self.sendSuperUpdate()
        elif t == BLOCK_PUPDATE:
            debug("Pupdate")
            for update in block.getUpdates():
                # Notify UI
                for l in self.listeners:
                    l.statusChanged(update)
                # Propagate it to other nodes if appropriate
                if self.isSuper:
                    for q in self.updateQueue.values():
                        # Don't queue back to originator
                        if q.peer == peer:
                            continue
                        q.addUpdate(update)
                    # Node is an underling, reply with status to it
                    if not nid in self.supers:
                        updates = self.updateQueue[nid].getUpdates()
                        if len(updates) > 0:
                            pu = PlayerUpdateBlock.create(self.lastTick, updates)
                            peer.send().addBlock(pu)
                        else:
                            debug("%s No updates to send?" % peer)
        return True

    def _statusChanged(self, status):
        assert isinstance(status, NodeSimpleStatus)
        for l in self.listeners:
            l.statusChanged(status)

    def registerStatusListener(self, listener):
        assert isinstance(listener, StatusChangeListener)
        if not listener in self.listeners:
            self.listeners.append(listener)

    def flushQueue(self, tick):
        for q in self.updateQueue.values():
            peer = q.peer
            # We only send regulary to other supers
            # normal peers get their as a reply to the update
            if not peer.getId() in self.supers:
                continue
            updates = q.getUpdates()
            if len(updates) > 0:
                pu = PlayerUpdateBlock.create(tick, updates)
                seq = peer.send().addBlock(pu)
                # TODO: Error handling?

    def maybeConnectSupers(self):
        if len(self.supers) < 2 and not self.isSuper:
            self.isSuper = True
            self.sendSuperUpdate()
        maxSupers = 0
        connected = 0
        if not self.isSuper:
            maxSupers = 2
            for sup in self.supers.values():
                if sup.state == PeerState.CONNECTED:
                    connected += 1

        if maxSupers == 0 or connected < maxSupers:
            for sup in self.supers.values():
                if sup.state == PeerState.DISCONNECTED:
                    debug("Connecting to super %s" % sup)
                    sup.connect()


    def queueUpdate(self, ss):
        assert isinstance(ss, NodeSimpleStatus)

        self.gameStates[ss.nodeid] = ss
        for q in self.updateQueue.values():
            q.addUpdate(ss)

    def sendUpdate(self, ss, tick):
        """ Called by the local node to send it's updated status out """
        self.lastTick = tick
        self.maybeConnectSupers()
        self.queueUpdate(ss)
        self.flushQueue(tick)

    def peerStateChanged(self, peer, peerstate):
        nid = peer.getId()
        if peerstate in (PeerState.STALE, PeerState.DISCONNECTING):
            if nid in self.peers:
                del self.peers[nid]
            if nid in self.updateQueue:
                del self.updateQueue[nid]
            if nid in self.supers:
                del self.supers[nid]
            peer.delStateListener(self)
        elif peerstate == PeerState.CONNECTED:
            if nid in self.supers:
                debug("super connected %s" % peer)
                if self.isSuper:
                    # Supers don't ask, just send :)
                    self.createUpdateQueue(peer)
                else:
                    # Standard nodes need to be well behaved and ask permission
                    self.joinSuper(peer)
