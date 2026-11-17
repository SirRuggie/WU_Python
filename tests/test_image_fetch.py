"""Offline transport regressions: real Requests/urllib3, fixture sockets only."""

import io
import socket
from types import SimpleNamespace

import pytest
import requests
import urllib3.connection

from utils import image_fetch, url_safety
from utils.url_safety import MAX_IMAGE_BYTES


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(dns=[], connects=[], tls=[], sockets=[], headers=b"", body=b"ok", status=200, extra=b"")

    def resolve(host, port, *args, **kwargs):
        state.dns.append(host)
        # A second lookup of the original name simulates rebinding to loopback.
        address = "93.184.216.34" if state.dns.count("image.example") == 1 else "127.0.0.1"
        if host != "image.example":
            address = host
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    class FixtureSocket:
        def __init__(self, *args):
            state.sockets.append(self)
            self.closed = False

        def setsockopt(self, *args):
            pass

        def settimeout(self, *args):
            pass

        def connect(self, address):
            state.connects.append(address)

        def sendall(self, data):
            state.headers += data

        def makefile(self, *args, **kwargs):
            return io.BytesIO(
                f"HTTP/1.1 {state.status} Fixture\r\n".encode()
                + state.extra + b"Connection: close\r\n\r\n" + state.body
            )

        def close(self):
            self.closed = True

    def wrap(**kwargs):
        state.tls.append(kwargs)
        return SimpleNamespace(socket=kwargs["sock"], is_verified=True)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "socket", FixtureSocket)
    monkeypatch.setattr(urllib3.connection, "_ssl_wrap_socket_and_match_hostname", wrap)
    return state


def test_rebinding_cannot_change_socket_destination_and_https_identity(transport):
    assert image_fetch.fetch_public_image("https://image.example:8443/a.png?q=one") == b"ok"
    assert transport.dns == ["image.example", "93.184.216.34"]
    assert transport.connects == [("93.184.216.34", 8443)]
    assert b"Host: image.example:8443\r\n" in transport.headers
    assert b"GET /a.png?q=one HTTP/1.1" in transport.headers
    assert transport.tls[0]["server_hostname"] == "image.example"
    assert transport.tls[0]["assert_hostname"] == "image.example"
    assert transport.tls[0]["cert_reqs"] == "CERT_REQUIRED"
    assert all(sock.closed for sock in transport.sockets)


@pytest.mark.parametrize("entry", [image_fetch.fetch_public_image, image_fetch.download_image_blocking])
@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::ffff:127.0.0.1"])
def test_all_download_entries_refuse_private_destinations_before_socket(monkeypatch, transport, entry, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))])
    with pytest.raises(ValueError, match="non-public"):
        entry("http://image.example/a.png")
    assert transport.connects == []


def test_mixed_dns_answer_is_rejected_before_any_connection(monkeypatch, transport):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))
        for ip in ("93.184.216.34", "192.168.1.5")
    ])
    with pytest.raises(ValueError, match="non-public"):
        image_fetch.fetch_public_image("http://image.example/a.png")
    assert transport.connects == []


def test_proxy_environment_and_netrc_are_ignored(monkeypatch, transport):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1234")
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", lambda *a: pytest.fail("netrc was consulted"))
    assert image_fetch.fetch_public_image("http://image.example/a.png") == b"ok"
    assert transport.connects == [("93.184.216.34", 80)]
    assert b"GET /a.png HTTP/1.1" in transport.headers


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_rejected_without_fetching_location(transport, status):
    transport.status = status
    transport.extra = b"Location: http://127.0.0.1/private.png\r\n"
    with pytest.raises(requests.HTTPError):
        image_fetch.fetch_public_image("http://image.example/a.png")
    assert len(transport.connects) == 1
    assert transport.dns.count("image.example") == 1


def test_small_body_is_returned_whole(transport):
    transport.body = b"abcdef"
    transport.extra = b"Content-Length: 6\r\n"
    assert image_fetch.download_image_blocking("http://image.example/attachment") == b"abcdef"


def test_declared_size_over_the_cap_is_refused(transport):
    transport.extra = f"Content-Length: {MAX_IMAGE_BYTES + 1}\r\n".encode()
    with pytest.raises(ValueError, match="10 MB"):
        image_fetch.download_image_blocking("http://image.example/a.png")
    assert all(sock.closed for sock in transport.sockets)


def test_streamed_size_over_the_cap_is_refused(transport):
    transport.body = b"x" * (MAX_IMAGE_BYTES + 1)
    with pytest.raises(ValueError, match="10 MB"):
        image_fetch.download_image_blocking("http://image.example/a.png")


def test_failure_does_not_retry_or_fall_back_to_dns(monkeypatch, transport):
    def fail(self, address):
        transport.connects.append(address)
        raise OSError("fixture failure")

    # The constructor is the socket fixture, so patch its connect method.
    monkeypatch.setattr(socket.socket, "connect", fail)
    with pytest.raises(requests.ConnectionError):
        image_fetch.fetch_public_image("http://image.example/a.png")
    assert transport.connects == [("93.184.216.34", 80)]
    assert transport.dns == ["image.example", "93.184.216.34"]


def test_connect_and_read_timeouts_are_retained(monkeypatch, transport):
    seen = []
    original = requests.Session.send

    def send(self, request, **kwargs):
        seen.append((self.trust_env, kwargs["timeout"], kwargs["allow_redirects"], kwargs["stream"]))
        return original(self, request, **kwargs)

    monkeypatch.setattr(requests.Session, "send", send)
    assert image_fetch.fetch_public_image("http://image.example/a.png") == b"ok"
    assert seen == [(False, (5, 15), False, True)]


def test_public_entry_still_requires_image_extension(transport):
    with pytest.raises(ValueError, match="directly"):
        image_fetch.fetch_public_image("http://image.example/attachment")
    assert transport.dns == []


def test_certificate_failure_is_not_suppressed_or_retried(monkeypatch, transport):
    from urllib3.exceptions import SSLError

    def reject(**kwargs):
        assert kwargs["assert_hostname"] == "image.example"
        assert kwargs["cert_reqs"] == "CERT_REQUIRED"
        raise SSLError("fixture hostname mismatch")

    monkeypatch.setattr(urllib3.connection, "_ssl_wrap_socket_and_match_hostname", reject)
    with pytest.raises(requests.exceptions.SSLError, match="hostname mismatch"):
        image_fetch.fetch_public_image("https://image.example/a.png")
    assert transport.connects == [("93.184.216.34", 443)]
