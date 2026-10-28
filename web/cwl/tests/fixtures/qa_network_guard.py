"""Test-only outbound network guard: local fixture servers only."""
import socket
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex

def _allowed(address):
    if isinstance(address, str):
        raise RuntimeError('QA forbids UNIX sockets to prevent access to live services')
    if isinstance(address, tuple) and str(address[0]) not in ('127.0.0.1', '::1', 'localhost'):
        raise RuntimeError('QA forbids outbound network connections')
    if isinstance(address, tuple) and address[1] in (8766, 8767, 27017, 5432, 6379, 3306, 443, 80):
        raise RuntimeError('QA forbids default service ports')

def connect(self, address):
    _allowed(address)
    return _original_connect(self, address)

def connect_ex(self, address):
    _allowed(address)
    return _original_connect_ex(self, address)
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
