"""Resolve user image links once and classify every possible destination."""

from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlparse, urlunparse

ALLOWED_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MAX_IMAGE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class PublicImageTarget:
    """A normalized URL and the numeric addresses approved for this request."""

    url: str
    scheme: str
    host: str
    port: int
    authority: str
    addresses: tuple[str, ...]


def resolve_public_image_url(url: str, *, require_image_extension: bool = True) -> PublicImageTarget:
    """Resolve once, rejecting the entire answer if any address is non-public.

    This result must be used to pin the connection; a boolean precheck alone
    cannot prevent DNS rebinding. Direct attachment downloads may omit the file
    extension, since their callers validate the attachment and decoded bytes.
    """
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ValueError("URL is missing or too long.")
    url = url.strip()
    if any(ord(char) < 33 or ord(char) == 127 for char in url) or "\\" in url:
        raise ValueError("URL could not be parsed.")
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URL must not contain credentials.")
        if not host:
            raise ValueError("URL has no host.")
        host = host.encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError) as exc:
        raise ValueError("URL could not be parsed.") from exc
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://.")
    if require_image_extension and not parsed.path.lower().endswith(ALLOWED_IMAGE_EXTS):
        raise ValueError("URL must point directly to a .png/.jpg/.jpeg/.gif/.webp image.")
    port = port if port is not None else (443 if parsed.scheme == "https" else 80)
    if port == 0 or "%" in host:
        raise ValueError("URL could not be parsed.")
    try:
        addrinfos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("URL host could not be resolved.") from exc
    if not addrinfos:
        raise ValueError("URL host could not be resolved.")
    addresses = []
    for info in addrinfos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError as exc:
            raise ValueError("URL resolved to an invalid address.") from exc
        classified = address.ipv4_mapped if address.version == 6 and address.ipv4_mapped else address
        if (not classified.is_global or classified.is_multicast or classified.is_reserved):
            raise ValueError("URL resolves to a non-public address.")
        if str(address) not in addresses:
            addresses.append(str(address))
    authority = f"[{host}]" if ":" in host else host
    if parsed.port is not None:
        authority += f":{port}"
    normalized = urlunparse((parsed.scheme, authority, parsed.path or "/", parsed.params, parsed.query, ""))
    return PublicImageTarget(normalized, parsed.scheme, host, port, authority, tuple(addresses))


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """Compatibility precheck; fetching must use the checked-address transport."""
    try:
        resolve_public_image_url(url)
    except ValueError as exc:
        return False, str(exc)
    return True, ""
