# Author: Roger Blomgren <roger.blomgren@iki.fi>
class STQPacketException(Exception):
    def __init__(self, msg):
        super().__init__(msg)
