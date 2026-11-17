"""Blocking, checked-address image downloads; call through asyncio.to_thread."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool

from utils.url_safety import MAX_IMAGE_BYTES, PublicImageTarget, resolve_public_image_url


class _CheckedAddressAdapter(HTTPAdapter):
    """Keep the HTTP/TLS hostname while the pool connects to a checked IP.

    One request owns this adapter and pool. There is no fallback resolution,
    proxy, redirect, or retry to an unchecked destination.
    """

    def __init__(self, target: PublicImageTarget):
        super().__init__(max_retries=0)
        if target.scheme == "https":
            self.checked_pool = HTTPSConnectionPool(
                target.addresses[0], target.port,
                server_hostname=target.host, assert_hostname=target.host,
            )
        else:
            self.checked_pool = HTTPConnectionPool(target.addresses[0], target.port)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        if proxies:
            raise ValueError("Image downloads do not support proxies.")
        return self.checked_pool

    def get_connection(self, url, proxies=None):
        """Requests <2.32 compatibility; same checked pool."""
        if proxies:
            raise ValueError("Image downloads do not support proxies.")
        return self.checked_pool

    def close(self):
        self.checked_pool.close()
        super().close()


def _download(target: PublicImageTarget) -> bytes:
    with requests.Session() as session:
        session.trust_env = False
        session.mount(f"{target.scheme}://", _CheckedAddressAdapter(target))
        with session.get(
            target.url, headers={"Host": target.authority},
            timeout=(5, 15), allow_redirects=False, stream=True,
        ) as resp:
            resp.raise_for_status()
            if not 200 <= resp.status_code < 300:
                raise requests.HTTPError("Image URL did not return a successful response.", response=resp)
            declared = resp.headers.get("Content-Length")
            if declared is not None and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
                raise ValueError("Image is larger than the 10 MB limit.")
            chunks = []
            total = 0
            for chunk in resp.iter_content(8192):
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise ValueError("Image is larger than the 10 MB limit.")
                chunks.append(chunk)
            return b"".join(chunks)


def download_image_blocking(url: str) -> bytes:
    """Guard direct attachment/migration callers, including extensionless URLs."""
    return _download(resolve_public_image_url(url, require_image_extension=False))


def fetch_public_image(url: str) -> bytes:
    """Fetch a user-entered image URL with one resolution and a pinned socket."""
    return _download(resolve_public_image_url(url))
