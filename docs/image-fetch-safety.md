# Image fetch safety

Decision 239 Part I (2026-11-17): image downloads resolve the requested hostname
once, classify every DNS answer, and connect only to a numeric address from that
checked answer. The connection pool uses the first checked address. It does not
fall back to DNS or retry another address after a connection failure.

`utils/url_safety.py` owns parsing and classification. All answers must be global
unicast addresses; private, loopback, link-local, multicast, reserved,
unspecified, shared address space and IPv4-mapped private IPv6 answers fail.
Mixed public/private answers fail as a whole. IPv4-mapped IPv6 is classified by
its embedded IPv4. Scoped IPv6, URL credentials, malformed/zero/out-of-range
ports, backslashes and embedded control/whitespace characters are refused.
HTTP and HTTPS custom ports remain supported.

`utils/image_fetch.py` owns the blocking download boundary. A Requests adapter
returns a per-request urllib3 pool whose host is the checked numeric IP. The
original normalized hostname remains the HTTP `Host` header (with brackets for
IPv6 and any explicit port), TLS SNI name and certificate verification hostname.
Certificate verification remains required. Numeric socket resolution in urllib3
cannot re-resolve the original hostname. The session sets `trust_env=False`, so
proxy environment variables, netrc credentials and environment CA overrides
cannot redirect or authenticate these downloads.

Both `fetch_public_image` and `download_image_blocking` enforce this boundary.
The former still requires an image filename extension. The latter preserves
extensionless attachment/Cloudinary support: callers validate attachments and
image bytes. Direct callers are `utils/cwl_media.py`,
`extensions/commands/clan/dashboard/image_uploads.py` and
`tools/migrate_media_to_r2.py`. No caller can bypass the network guard by using
the direct function. `is_safe_public_url` preserves its `(bool, reason)` API for
validation, but a precheck alone is not a safe fetch mechanism.

Downloads permit no redirects, require a 2xx response, use 5-second connect and
15-second per-read timeouts, and cap declared and decoded streamed bodies at
10 MiB. Responses, pools and sessions close on success or failure. DNS uses the
system resolver, whose own timeout policy is unchanged. Per-read timeouts do not
bound total elapsed time for a slow stream. There is no global deadline here.
No dependency, storage, route, permission or production data change is required.

Offline regression tests exercise the real Requests/urllib3 stack against fixture
sockets: DNS rebinding, mixed/private answers, HTTP Host, TLS SNI and certificate
verification parameters, verification failure propagation, proxy/netrc bypass,
custom ports, redirect refusal, failure without retries, and size/time limits.
TLS wrapping is mocked; this proves transport configuration and failure
handling, not a live TLS handshake or live image/CDN availability. No live image,
Discord, Clash or production database calls are part of these checks.
