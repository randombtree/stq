# STQ

This is a course work assignment submission; it might be an interesting
starting point for learning event-based network programming (YMMV). Appended
here is a slightly modified readme returned as part of the assignment.
Note that the code contains numerous bugs and deficiencies (as the time
assigned for the assignment was 2 weeks).


# Introduction

The Space Trade Quest game is built on a P2P network where the game server
essentially only serves as a hookup point for the clients. Originally there was
supposed to be a network of servers working as a "cloud", giving clients the
option to join any server in the cloud to connect. That feature was
unfortunately not completed in time for the submission. Servers can be chained
in the actual implementation but all topology information is unfortunately not
yet propagated due to missing code/bugs. The original design had a dynamic
super-node allocation scheme where different space areas had different
super-nodes. Currently clients just take a super-node position if they don’t
find two other nodes to serve as a super-node. There is no performance
monitoring of super nodes and no super-node voting mechanisms present. Most
error conditions such as dropping nodes are handled poorly - clients
disconnecting will not remove the ship from view. Saving and recovering after
closing the client connection is not implemented. Most of the protocol resend
logic is using static timeouts and RTT is not calculated. The GUI is rather
simple. Visible ships are shown around the player and movement is possible.

# Usage

## Requirements

STQ uses a few non-standard python3 modules, namely twisted (python3-twisted),
pysdl2 (python3-sdl2), netifaces (python3-netifaces) and monotime
(python3-monotime).  Make sure you have them installed with your
package-manager or pip (i.e. `python3 -m pip install <package>`).

## Server

The server is started with a specific port number as a parameter. This will be
the port number the client connects to.

  > ./server.py 1337

## Client

The client connect to the server using the server host address and port
number. When running both server and client locally, "127.0.0.1" can be used.

 > ./client.py 127.0.0.1 1337 MyHandle

When the client starts, it immediately connects to the server and displays the
space view. The spaceship can be controlled with the arrow keys. Left, Right
for turn and Up for throttle and Down for brake. Collision detection (or
anything else really) isn’t implemented. Multiple clients can connect to the
same server. If using multi-host configuration, be sure to not use the local
host address "127.0.0.1" as a destination address for the client as it confuses
the client address discovery (bug/implementation deficiency).

