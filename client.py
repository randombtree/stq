#!/usr/bin/env python3
# Author: Roger Blomgren <roger.blomgren@iki.fi>
import sys
import socket
import random
import getopt
from enum import Enum

from twisted.internet import reactor
from protocol import STQProtocolHandler

from common import set_debug, Ticker
from debug import debug
from node import NodeRole, STQNode, BlockReceiver
from address import *
from blocks import *
from game import GameHandler
from supernode import *

class ClientState(Enum):
    STARTING = 0
    CONNECTING = 1
    SUPER = 2
    OLDSUPER = 3
    NODE = 4
class ClientHandler(BlockReceiver, Ticker, StatusChangeListener):
    def __init__(self, node):
        Ticker.__init__(self)

        self.node = node
        self.node.registerReceiver(BLOCK_STARTED, self)
        self.state = ClientState.STARTING
        self.gamestatus = None
        self.game = None
        self.supernode = None
        self.game = GameHandler()

    def stateChanged(self, state):
        self.state = state

    def statusChanged(self, simpleStatus):
        """ Callback from supernode """
        debug("update: %s" % (simpleStatus,))
        if self.game:
            self.game.statusChange(simpleStatus)

    def received(self, peer, block):
        t = block.getType()
        if self.state == ClientState.STARTING and t == BLOCK_STARTED:
            self.gamestatus = block.status.simplestatus
            debug("Got startblock: %s" % (self.gamestatus,))
            debug("Initial tick %d" % (self.gamestatus.tick))
            self.setTick(self.gamestatus.tick)
            debug("Servers:")
            for server in block.servers:
                debug("- %s" % (server,))
            supers = block.supers
            if len(supers) > 0:
                debug("Supers:")
            for sup in supers:
                debug("- %s" % (sup))
            self.supernode = SuperNode(self.node, supers = supers)
            self.supernode.registerStatusListener(self)
            self.stateChanged(ClientState.SUPER)
            self.game.start(block.status)
            debug("Return to caller")
            return True

    def tickHappened(self, tick):
        assert tick > 0 and tick < 1 << 16
        if self.game.running:
            self.game.handleEvents(self)
            if not self.game.running:
                reactor.stop()
            else:
                ss = self.game.getStatus()
                if ss:
                    debug("Our status: %s" % ss)
                    self.supernode.sendUpdate(ss, tick)

def help(args):
    print("%s: <server> <port> <name>" % (args[0],))
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
    if len(restarg) != 3:
        return help(args)
    node = STQNode()
    try:
        port = int(restarg[1])
        host = socket.getaddrinfo(restarg[0], port, proto = socket.IPPROTO_UDP)
        name = restarg[2]
    except ValueError as e:
        print("Invalid port")
        return help(args)
    except socket.gaierror as e:
        print("Invalid host");
        return help(args)

    # getaddrinfo gives us so much more, but
    # it's outside of this project scope
    node.addServer(NodeAddress(host[0]))
    handler = ClientHandler(node)
    node.setName(name)
    node.start()
    reactor.run()

if __name__ == "__main__":
    sys.exit(main(sys.argv))
