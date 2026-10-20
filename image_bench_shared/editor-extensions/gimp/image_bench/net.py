"""
Connecting to the server. socket.create_connection tries the addresses of a host name in the resolver's order, each
until it times out: a machine name of the local network (http://rtx:7860) resolving to an unreachable link-local IPv6
address first made every request wait for its timeout. Here IPv4 comes first, link-local IPv6 addresses without an
interface are left out, each address gets a short connect timeout, and the address that worked is remembered.
"""
import http.client
import ipaddress
import socket
import ssl
import threading

# Seconds to wait for each address of the host; the server is on this computer or the local network
CONNECT_TIMEOUT = 3

_lock = threading.Lock()
# (host, port) -> the sockaddr that connected last, with its family
_working = {}


def _addresses(host, port):
    result = []

    for family, _, _, _, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        if family == socket.AF_INET6:
            address = ipaddress.ip_address(sockaddr[0].split("%")[0])

            # Not reachable without the interface (scope id), which a name lookup does not give
            if address.is_link_local and not sockaddr[3]:
                continue

        if (family, sockaddr) not in result:
            result.append((family, sockaddr))

    # IPv4 first, keeping the resolver's order otherwise
    return sorted(result, key=lambda entry: entry[0] != socket.AF_INET)


def connect(host, port, timeout):
    """A socket connected to host:port, with the given timeout for its reads and writes"""
    with _lock:
        known = _working.get((host, port))

    candidates = ([known] if known else []) + [entry for entry in _addresses(host, port) if entry != known]
    error = OSError(f"No address found for {host}")

    for family, sockaddr in candidates:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(min(CONNECT_TIMEOUT, timeout) if timeout else CONNECT_TIMEOUT)

        try:
            sock.connect(sockaddr)
        except OSError as e:
            sock.close()
            error = e
            continue

        sock.settimeout(timeout)

        with _lock:
            _working[(host, port)] = (family, sockaddr)

        return sock

    with _lock:
        _working.pop((host, port), None)

    raise error


class HTTPConnection(http.client.HTTPConnection):

    def connect(self):
        self.sock = connect(self.host, self.port, self.timeout)


class HTTPSConnection(http.client.HTTPSConnection):

    def connect(self):
        sock = connect(self.host, self.port, self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
