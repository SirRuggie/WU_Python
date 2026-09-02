"""The guarded image download shared by the emoji flow and the media store."""

import pytest

from utils import image_fetch
from utils.url_safety import MAX_IMAGE_BYTES


class _Response:
    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, _size):
        yield from self._chunks


def test_small_body_is_returned_whole(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response([b"abc", b"def"], {"Content-Length": "6"})

    monkeypatch.setattr(image_fetch.requests, "get", fake_get)
    assert image_fetch.download_image_blocking("https://x.example.com/a.png") == b"abcdef"
    url, kwargs = calls[0]
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["timeout"] == (5, 15)


def test_declared_size_over_the_cap_is_refused_before_reading(monkeypatch):
    def fake_get(url, **kwargs):
        return _Response([b"x"], {"Content-Length": str(MAX_IMAGE_BYTES + 1)})

    monkeypatch.setattr(image_fetch.requests, "get", fake_get)
    with pytest.raises(ValueError, match="10 MB"):
        image_fetch.download_image_blocking("https://x.example.com/a.png")


def test_streamed_size_over_the_cap_is_refused(monkeypatch):
    def fake_get(url, **kwargs):
        chunk = b"\0" * 8192
        return _Response([chunk] * (MAX_IMAGE_BYTES // 8192 + 2))

    monkeypatch.setattr(image_fetch.requests, "get", fake_get)
    with pytest.raises(ValueError, match="10 MB"):
        image_fetch.download_image_blocking("https://x.example.com/a.png")


def test_fetch_public_image_refuses_before_any_request(monkeypatch):
    monkeypatch.setattr(image_fetch, "is_safe_public_url", lambda url: (False, "URL resolves to a non-public address."))

    def never(url, **kwargs):
        raise AssertionError("requests.get must not be called")

    monkeypatch.setattr(image_fetch.requests, "get", never)
    with pytest.raises(ValueError, match="non-public address"):
        image_fetch.fetch_public_image("http://169.254.169.254/x.png")


def test_fetch_public_image_downloads_when_safe(monkeypatch):
    monkeypatch.setattr(image_fetch, "is_safe_public_url", lambda url: (True, ""))
    monkeypatch.setattr(image_fetch.requests, "get", lambda url, **kw: _Response([b"ok"]))
    assert image_fetch.fetch_public_image("https://x.example.com/a.png") == b"ok"
