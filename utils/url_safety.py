"""URL safety checks for user-supplied image links.

Used before the bot fetches an image from a URL a user typed (e.g. clan
emoji/logo uploads). Guards against SSRF: the bot must not be tricked into
fetching internal addresses like cloud metadata (169.254.169.254), localhost,
or private-network hosts.
"""

import ipaddress
import socket
from urllib.parse import urlparse

# Only fetch things that look like images.
ALLOWED_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Hard cap on how many bytes we will pull from a remote image, so a hostile
# or broken URL cannot stream gigabytes into memory and OOM the shared box.
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """Return (ok, reason) for whether `url` is safe for the bot to fetch.

    Safe means: http/https, an image file extension, and a host that resolves
    ONLY to public IP addresses. Any private, loopback, link-local, multicast,
    reserved, or unspecified address causes rejection. `reason` is a short,
    user-facing explanation when ok is False (empty string when ok is True).
    """
    if not url or len(url) > 2048:
        return False, "URL is missing or too long."

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False, "URL could not be parsed."

    if parsed.scheme not in ("http", "https"):
        return False, "URL must start with http:// or https://."

    host = parsed.hostname
    if not host:
        return False, "URL has no host."

    if not parsed.path.lower().endswith(ALLOWED_IMAGE_EXTS):
        return False, "URL must point directly to a .png/.jpg/.jpeg/.gif/.webp image."

    # Resolve the host and require EVERY resolved address to be public. Doing the
    # classification on the resolved IPs (not on the text of the URL) is what
    # defeats encoded-IP tricks (decimal/octal/hex) and hostnames pointed at
    # internal ranges: they all reduce to an IP we can classify.
    try:
        addrinfos = socket.getaddrinfo(host, None)
    except Exception:
        return False, "URL host could not be resolved."

    if not addrinfos:
        return False, "URL host could not be resolved."

    for info in addrinfos:
        ip_text = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            return False, "URL resolved to an invalid address."
        # An IPv4-mapped IPv6 address (e.g. ::ffff:127.0.0.1) must be judged by
        # its embedded IPv4, or an internal target slips past on interpreters
        # older than 3.11.10 / 3.12.5 / 3.13 whose ipaddress module does not
        # delegate these properties to the mapped address.
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "URL resolves to a non-public address."

    return True, ""
