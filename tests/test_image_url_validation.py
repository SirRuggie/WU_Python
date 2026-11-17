"""Tests for the SSRF guard on user-supplied image URLs.

These are offline: every case uses an IP-literal or localhost host, so
socket.getaddrinfo resolves without touching the network. We do NOT test the
actual HTTP download here, because that needs a live connection.
"""

import pytest

from utils.url_safety import is_safe_public_url


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/x.png",  # cloud metadata (link-local)
    "http://127.0.0.1/x.png",                          # loopback v4
    "http://localhost/x.png",                          # loopback by name
    "http://[::1]/x.png",                              # loopback v6
    "http://10.0.0.1/x.png",                           # private range
    "http://192.168.1.1/x.png",                        # private range
    "http://172.16.0.1/x.png",                         # private range
    "http://0.0.0.0/x.png",                            # unspecified
    "http://2130706433/x.png",                         # decimal-encoded 127.0.0.1
    "http://[::ffff:127.0.0.1]/x.png",                 # IPv4-mapped IPv6 loopback
    "http://[::ffff:169.254.169.254]/x.png",           # IPv4-mapped IPv6 metadata
    "http://[64:ff9b::7f00:1]/x.png",                  # NAT64-embedded loopback
    "file:///etc/passwd",                              # non-http scheme
    "ftp://example.com/x.png",                         # non-http scheme
    "https://example.com/payload.exe",                 # not an image extension
    "https://example.com/no-extension",                # no image extension
    "notaurl",                                         # unparseable, no scheme
    "",                                                # empty
])
def test_rejects_unsafe_urls(url):
    ok, reason = is_safe_public_url(url)
    assert ok is False, f"should have rejected {url!r} (reason={reason!r})"


@pytest.mark.parametrize("url", [
    "https://93.184.216.34/logo.png",     # public IPv4 literal, png
    "http://93.184.216.34/a/b/c.jpeg",    # nested path, jpeg
    "https://8.8.8.8/icon.webp",          # public IPv4 literal, webp
])
def test_allows_safe_public_image_urls(url):
    ok, reason = is_safe_public_url(url)
    assert ok is True, f"should have allowed {url!r} (reason={reason!r})"


@pytest.mark.parametrize("url", [
    "https://user:password@example.com/a.png",
    "https://example.com:invalid/a.png",
    "https://example.com:99999/a.png",
    "https://example.com:0/a.png",
    "https://[broken/a.png",
    "https://example.com\\@127.0.0.1/a.png",
    "https://example.com/\na.png",
    "https://[fe80::1%25eth0]/a.png",
    None,
])
def test_malformed_urls_are_safe_failures(url):
    ok, reason = is_safe_public_url(url)
    assert not ok
    assert reason


def test_resolution_failure_is_a_safe_failure(monkeypatch):
    import socket

    def fail(*args, **kwargs):
        raise socket.gaierror("fixture failure")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert is_safe_public_url("https://image.example/a.png") == (False, "URL host could not be resolved.")
