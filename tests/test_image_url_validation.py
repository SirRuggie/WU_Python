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
