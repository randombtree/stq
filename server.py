#!/usr/bin/env python3
# Author: Roger Blomgren <roger.blomgren@iki.fi>
import sys
import socket
import random
import getopt

from twisted.internet import reactor

from node import NodeRole, STQNode, BlockReceiver, PacketListener
from common import set_debug, TICK_LENGTH, Ticker
from address import *
from blocks import *
from util import make_nodeid
from gamedata import *
from supernode import *

class ServerHandler(BlockReceiver, Ticker):
    def __init__(self, node):
        Ticker.__init__(self)
        self.node = node
        self.peers = []
        self.node.registerReceiver(BLOCK_SGAME, self)
        self.nodes = []
        self.superNode = SuperNode(self.node, True)

    def addNode(self, peer):
        if not peer in self.nodes:
            debug("New node %s" % (peer,))
            self.nodes.append(peer)

    def receiveSgame(self, peer, block):
        # Peer wants to start a new game
        debug("%s tries to start a new game" % (peer,))
        addr = peer.addr.addr
        if not addr.valid_id():
            # Create new nodeaddress, the peer will use this
            # in the future
            nodeid = make_nodeid()
            addr = NodeAddress(addr.addrinfo, nodeid)

        ss = NodeSimpleStatus(addr.nodeid,
                              0,
                              0,
                              0,
                              0,
                              self.getTick())
        ss = NodeStatus(ss, block.nodeStatus().name)
        supers = self.superNode.getSupers()
        if len(supers) > 0:
            debug("***** SENDING SUPERS *******")
        for sup in supers:
            debug(" - %s" % (sup,))
        reply = StartedBlock.create(0,
                                    addr,
                                    ss,
                                    self.node.getConnectedServers(),
                                    supers)
        class WaitACK(PacketListener):
            def __init__(self, handler):
                self.handler = handler
                self.started = monotime_ms()

            def acked(self, seq):
                debug("%s is now connected" % (peer,))
                peer.setId(nodeid)
                peer.setState(PeerState.CONNECTED)
                self.handler.addNode(peer)

            def lost(self, seq):
                if self.started < monotime_ms() - 3000:
                    debug("%s lost a packet? Resend" % (peer,))
                    do_send_ss(self)
                else:
                    debug("%s timeout sending start game" % (peer,))

        def do_send_ss(l):
            seq = peer.send().addBlock(reply)
            peer.trackPacket(seq, l)
        peer.setState(PeerState.CONNECTING)
        do_send_ss(WaitACK(self))
        return True


    def received(self, peer, block):
        t = block.getType()
        if t == BLOCK_SGAME:
            return self.receiveSgame(peer, block)

    def tickHappened(self, tick):
        self.superNode.flushQueue(tick)

def help(args):
    print("%s: <port> [<srvhost> <port>]" % (args[0],))
    return 1

def main(args):
    debug.setDebug(False)
    try:
        opts = getopt.getopt(args[1:], 'dh')
    except getopt.GetoptError as e:
        print(e)
        return help(args)
    for o, a in opts[0]:
        if o == '-d':
            debug.setDebug(True)
        elif o == '-h':
            return help(args)

    restarg = opts[1]
    random.seed()
    if len(restarg) < 1:
        return help(args)
    port = int(restarg[0])
    node = STQNode(port, NodeRole.SERVER)

    if len(restarg) == 3:
        host = restarg[1]
        port = int(restarg[2])
        srv = addrinfo(socket.AF_INET, host, port)
        node.addServer(NodeAddress(srv))
    elif len(restarg) != 1:
        return help(args)
    handler = ServerHandler(node)
    node.start()
    debug("Starting reactor")
    reactor.run()

if __name__ == "__main__":
    sys.exit(main(sys.argv))
