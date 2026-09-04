"""Cloudflare R2: where uploaded clan logos, banners and FWA base images live.

Cloudinary hosted these until September 2026. Its free plan meters
bandwidth, and one leaky render loop (docs/media-hosting.md) spent 116 GB of
a 25 GB allowance in a month. R2 meters storage and requests, both with free
allowances far above this bot's needs, and never charges for egress, so the
same mistake again cannot produce a bill.

What this module does:

  * `MediaStore.upload_bytes(data, folder=..., name=...)` validates that the
    bytes are a PNG/JPEG/GIF/WEBP, writes them to the bucket, and returns the
    PUBLIC URL to store in Mongo. Every reader of `clan_data.logo`,
    `clan_data.banner` and the FWA base maps keeps working unchanged because
    they only ever held a public https URL.
  * `MediaStore.upload_from_url(url, ...)` fetches a URL a person pasted
    (public hosts only, 10 MB cap, no redirects) and uploads the bytes.
  * `MediaStore.delete_url(url)` removes an object behind one of OUR URLs.
  * `MediaStore.upload_static_blocking(data, key=...)` and `object_sha256(key)`
    put/inspect the repo's static art (logos, banners, base placeholders)
    under a PLAIN key instead of a content-addressed one, so a caller can
    compare a local file's sha256 against the object's stored metadata and
    skip re-uploading anything unchanged. `check_static_bytes(data, key)`
    runs the same validation without uploading, for a `--dry-run` pass.
    See `tools/upload_static_media.py`.

Keys are CONTENT-ADDRESSED: `<folder>/<name>.<sha256[:10]>.<ext>`. Re-uploading
a changed logo produces a new key and therefore a new URL, which is what
keeps Cloudflare's cache and Discord's media proxy from ever showing a stale
image. Objects are stored with a one-year immutable Cache-Control for the
same reason. The old object is left behind unless the caller deletes it.

Configuration comes from five environment variables (docs/deployment.md):
R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET and
R2_PUBLIC_BASE_URL. Missing values do not stop the bot booting; they make
uploads fail closed with `MediaStoreNotConfigured`, whose message is fit to
show in a Discord reply.

boto3 is imported lazily inside `_s3()` so importing this module (and running
its tests) never needs network credentials or the SDK's import cost.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import quote, unquote, urlparse

from PIL import Image, UnidentifiedImageError

from utils.image_fetch import fetch_public_image
from utils.url_safety import MAX_IMAGE_BYTES

REQUIRED_ENV = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_PUBLIC_BASE_URL",
)

# Content-addressed keys never change meaning, so caches may keep them forever.
CACHE_CONTROL = "public, max-age=31536000, immutable"

# Static art keeps a plain name, so caches must revalidate it daily.
STATIC_CACHE_CONTROL = "public, max-age=86400"

# Pillow format name -> (key extension, Content-Type). The extension matters
# twice: Discord's proxy and utils/url_safety.py both judge a URL by it.
_FORMATS = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "MPO": ("jpg", "image/jpeg"),   # multi-picture JPEGs straight off a phone
    "GIF": ("gif", "image/gif"),
    "WEBP": ("webp", "image/webp"),
}


class MediaStoreError(Exception):
    """Anything that stops an upload, worded for a Discord reply."""


class MediaStoreNotConfigured(MediaStoreError):
    """R2 settings are missing: uploads are off, nothing else is."""


@dataclass(frozen=True)
class MediaStoreConfig:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    public_base_url: str    # e.g. https://img.example.com - no trailing slash

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    @classmethod
    def from_env(cls) -> MediaStoreConfig | None:
        """The config from the environment, or None when any value is missing."""
        values = {name: os.getenv(name, "").strip() for name in REQUIRED_ENV}
        if not all(values.values()):
            return None
        return cls(
            account_id=values["R2_ACCOUNT_ID"],
            access_key_id=values["R2_ACCESS_KEY_ID"],
            secret_access_key=values["R2_SECRET_ACCESS_KEY"],
            bucket=values["R2_BUCKET"],
            public_base_url=values["R2_PUBLIC_BASE_URL"].rstrip("/"),
        )


def detect_image(data: bytes) -> tuple[str, str]:
    """`(extension, content_type)` for image bytes, else MediaStoreError.

    Pillow only reads the header here, so this is cheap even for a 10 MB
    file. The check exists because the slash commands validate the attachment
    NAME, and a renamed non-image would otherwise be served with an image
    extension and break silently inside Discord.
    """
    try:
        with Image.open(BytesIO(data)) as image:
            fmt = image.format
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise MediaStoreError("That file is not an image I can read.") from exc
    try:
        return _FORMATS[fmt or ""]
    except KeyError:
        raise MediaStoreError(
            f"Unsupported image format: {fmt}. Use PNG, JPG, GIF or WEBP."
        ) from None


def object_key(folder: str, name: str, data: bytes, ext: str) -> str:
    """`<folder>/<name>.<content hash>.<ext>` - see the module docstring."""
    digest = hashlib.sha256(data).hexdigest()[:10]
    folder = folder.strip("/")
    name = name.strip("/") or "image"
    return f"{folder}/{name}.{digest}.{ext}"


def check_static_bytes(data: bytes, key: str) -> tuple[str, str]:
    """`(ext, content_type)` for static art bytes, or MediaStoreError.

    The same empty/oversize/format/extension checks `upload_static_blocking`
    applies before it puts the object, factored out so
    `tools/upload_static_media.py`'s `--dry-run` path can reject exactly the
    files the real run would, without touching the network.
    """
    if not data:
        raise MediaStoreError("The file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaStoreError(
            f"Images must be under {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )
    ext, content_type = detect_image(data)
    key = key.strip("/")
    suffix = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    if suffix == "jpeg":
        suffix = "jpg"
    if suffix != ext:
        raise MediaStoreError(
            f"The file's bytes ({ext}) do not match its extension ({key})."
        )
    return ext, content_type


class MediaStore:
    """The bot's one handle on the bucket; registered for DI in main.py."""

    def __init__(self, config: MediaStoreConfig | None, *, client=None):
        self._config = config
        self._client = client    # tests inject a fake; production builds boto3

    @classmethod
    def from_env(cls) -> MediaStore:
        return cls(MediaStoreConfig.from_env())

    @property
    def configured(self) -> bool:
        return self._config is not None

    @property
    def public_base_url(self) -> str | None:
        return self._config.public_base_url if self._config else None

    def public_url(self, key: str) -> str:
        config = self._require_config()
        return f"{config.public_base_url}/{quote(key)}"

    def key_for_url(self, url: object) -> str | None:
        """The object key behind one of OUR public URLs, else None.

        Anything not under the configured base (a Cloudinary URL still in
        Mongo, a Discord CDN icon, a pasted link) is None: never a delete
        target, never mistaken for something this bucket holds.
        """
        if not self._config or not isinstance(url, str):
            return None
        prefix = self._config.public_base_url + "/"
        if not url.startswith(prefix):
            return None
        path = urlparse(url).path
        base_path = urlparse(self._config.public_base_url).path.rstrip("/")
        key = unquote(path[len(base_path):].lstrip("/"))
        return key or None

    # -- uploads -------------------------------------------------------------

    async def upload_bytes(self, data: bytes, *, folder: str, name: str) -> str:
        """Store image bytes; returns the public URL. Off the event loop."""
        return await asyncio.to_thread(
            self.upload_bytes_blocking, data, folder=folder, name=name
        )

    async def upload_from_url(self, url: str, *, folder: str, name: str) -> str:
        """Fetch a public image URL and store it; returns the public URL.

        Raises MediaStoreError for a URL that is not a direct public image
        link, a body over the size cap, or a non-2xx response.
        """
        try:
            data = await asyncio.to_thread(fetch_public_image, url)
        except MediaStoreError:
            raise
        except Exception as exc:
            raise MediaStoreError(f"Could not fetch that image: {exc}") from exc
        return await self.upload_bytes(data, folder=folder, name=name)

    def upload_bytes_blocking(self, data: bytes, *, folder: str, name: str) -> str:
        """The synchronous core of `upload_bytes`, for scripts and threads."""
        config = self._require_config()
        if not data:
            raise MediaStoreError("The file is empty.")
        if len(data) > MAX_IMAGE_BYTES:
            raise MediaStoreError(
                f"Images must be under {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
            )
        ext, content_type = detect_image(data)
        key = object_key(folder, name, data, ext)
        try:
            self._s3().put_object(
                Bucket=config.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl=CACHE_CONTROL,
            )
        except Exception as exc:
            raise MediaStoreError(f"Upload to R2 failed: {exc}") from exc
        return self.public_url(key)

    # -- static art ------------------------------------------------------------

    def object_sha256(self, key: str) -> str | None:
        """The `sha256` metadata stored on `key`, or None when it is missing.

        Lets a caller skip re-uploading a static file whose bytes have not
        changed since the last run. S3 returns user metadata keys lower-cased.
        """
        config = self._require_config()
        key = key.strip("/")
        try:
            response = self._s3().head_object(Bucket=config.bucket, Key=key)
        except Exception as exc:
            # botocore's HTTPClientError (and its ConnectionClosedError /
            # ResponseStreamingError subclasses) sets .response to None on a
            # transient network failure, and urllib3's InvalidChunkLength
            # sets it to an HTTPResponse -- neither is a dict, so guard the
            # type before calling .get() on it.
            resp = getattr(exc, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            if code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise MediaStoreError(f"Lookup in R2 failed: {exc}") from exc
        return response.get("Metadata", {}).get("sha256")

    def upload_static_blocking(self, data: bytes, *, key: str) -> str:
        """Store static art under a PLAIN key; returns the public URL.

        Unlike `upload_bytes_blocking`, the key is not content-addressed —
        the caller (`tools/upload_static_media.py`) picks it to mirror the
        repo's `assets/` layout, and re-uploads simply overwrite it.
        """
        config = self._require_config()
        ext, content_type = check_static_bytes(data, key)
        key = key.strip("/")
        try:
            self._s3().put_object(
                Bucket=config.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl=STATIC_CACHE_CONTROL,
                Metadata={"sha256": hashlib.sha256(data).hexdigest()},
            )
        except Exception as exc:
            raise MediaStoreError(f"Upload to R2 failed: {exc}") from exc
        return self.public_url(key)

    # -- deletes -------------------------------------------------------------

    async def delete_url(self, url: object) -> bool:
        """Delete the object behind one of OUR URLs. False if it is not ours."""
        key = self.key_for_url(url)
        if key is None:
            return False
        await asyncio.to_thread(self.delete_key_blocking, key)
        return True

    def delete_key_blocking(self, key: str) -> None:
        config = self._require_config()
        try:
            self._s3().delete_object(Bucket=config.bucket, Key=key)
        except Exception as exc:
            raise MediaStoreError(f"Delete from R2 failed: {exc}") from exc

    # -- internals -----------------------------------------------------------

    def _require_config(self) -> MediaStoreConfig:
        if self._config is None:
            raise MediaStoreNotConfigured(
                "Image storage is not configured on this bot. Set "
                + ", ".join(REQUIRED_ENV) + " in .env and restart."
            )
        return self._config

    def _s3(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            config = self._require_config()
            try:
                # botocore >= 1.36 adds CRC32 request checksums by default;
                # R2 documents Content-MD5 for PutObject and not those
                # headers, so keep the request plain. Older botocore has
                # neither the option nor the behaviour.
                options = Config(
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                )
            except TypeError:
                options = Config()
            self._client = boto3.client(
                "s3",
                endpoint_url=config.endpoint_url,
                aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key,
                region_name="auto",
                config=options,
            )
        return self._client
