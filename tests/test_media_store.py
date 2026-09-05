"""The R2 media store, against a fake S3 client.

Covers what the slash commands and the migration script rely on: image
sniffing, content-addressed keys, the public URL shape, failing closed when
unconfigured, and only ever deleting objects behind our own URLs.
"""

import asyncio
import hashlib
from io import BytesIO

import pytest
from PIL import Image

from utils import media_store
from utils.media_store import (
    CACHE_CONTROL,
    CLAN_BANNER,
    CLAN_LOGO,
    FWA_ACTIVE_BASE_NAME,
    FWA_WAR_BASE_NAME,
    STATIC_CACHE_CONTROL,
    MediaStore,
    MediaStoreConfig,
    MediaStoreError,
    MediaStoreNotConfigured,
    clan_folder,
    detect_image,
    fwa_base_folder,
    object_key,
)
from utils.url_safety import MAX_IMAGE_BYTES

CONFIG = MediaStoreConfig(
    account_id="acct",
    access_key_id="key",
    secret_access_key="secret",
    bucket="wu-media",
    public_base_url="https://img.example.com",
)


def image_bytes(fmt: str, color=(255, 0, 0)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, fmt)
    return buf.getvalue()


class FakeClientError(Exception):
    """Shaped like botocore's ClientError, without needing botocore."""

    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self, fail=None, head_response=None, head_fail=None):
        self.puts = []
        self.deletes = []
        self.head_calls = []
        self.fail = fail
        self.head_response = head_response
        self.head_fail = head_fail

    def put_object(self, **kwargs):
        if self.fail:
            raise self.fail
        self.puts.append(kwargs)

    def delete_object(self, **kwargs):
        if self.fail:
            raise self.fail
        self.deletes.append(kwargs)

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        if self.head_fail:
            raise self.head_fail
        return self.head_response or {}


def store_with(fake=None) -> tuple[MediaStore, FakeS3]:
    fake = fake or FakeS3()
    return MediaStore(CONFIG, client=fake), fake


# -- image sniffing --------------------------------------------------------

@pytest.mark.parametrize(("fmt", "ext", "content_type"), [
    ("PNG", "png", "image/png"),
    ("JPEG", "jpg", "image/jpeg"),
    ("GIF", "gif", "image/gif"),
    ("WEBP", "webp", "image/webp"),
])
def test_detect_image_maps_the_four_served_formats(fmt, ext, content_type):
    assert detect_image(image_bytes(fmt)) == (ext, content_type)


def test_detect_image_rejects_non_image_bytes():
    with pytest.raises(MediaStoreError, match="not an image"):
        detect_image(b"<html>definitely not a picture</html>")


def test_detect_image_rejects_formats_discord_will_not_render():
    with pytest.raises(MediaStoreError, match="Unsupported image format: BMP"):
        detect_image(image_bytes("BMP"))


# -- keys and URLs ---------------------------------------------------------

def test_object_key_is_content_addressed():
    data = image_bytes("PNG")
    digest = hashlib.sha256(data).hexdigest()[:10]
    key = object_key("clan_logos/Warriors_United/", "Arcane_Angels", data, "png")
    assert key == f"clan_logos/Warriors_United/Arcane_Angels.{digest}.png"
    assert object_key("clan_logos/Warriors_United", "Arcane_Angels", data, "png") == key
    other = object_key("clan_logos/Warriors_United", "Arcane_Angels", image_bytes("PNG", (0, 0, 255)), "png")
    assert other != key


def test_bucket_layout_helpers_and_name_constants():
    # Pins the layout the bucket and Mongo already hold, so a rename here is
    # a deliberate migration, not an accident.
    assert clan_folder("Arcane Angels!") == "clans/Arcane_Angels"
    assert clan_folder("Воины") == "clans/unnamed"
    assert fwa_base_folder("th16_new") == "fwa/bases/th16_new"
    assert (CLAN_LOGO, CLAN_BANNER, FWA_WAR_BASE_NAME, FWA_ACTIVE_BASE_NAME) == (
        "logo", "banner", "war", "active",
    )


def test_key_for_url_only_matches_our_own_base():
    store, _ = store_with()
    assert store.key_for_url("https://img.example.com/clan_logos/X.abc.png") == "clan_logos/X.abc.png"
    assert store.key_for_url("https://img.example.com/clan%20logos/X.png") == "clan logos/X.png"
    assert store.key_for_url("https://img.example.com.evil.test/clan_logos/X.png") is None
    assert store.key_for_url("https://res.cloudinary.com/x/image/upload/v1/X.png") is None
    assert store.key_for_url("https://img.example.com/") is None
    assert store.key_for_url(None) is None


# -- uploads ---------------------------------------------------------------

def test_upload_bytes_puts_the_object_and_returns_its_public_url():
    store, fake = store_with()
    data = image_bytes("PNG")
    url = asyncio.run(store.upload_bytes(data, folder="clan_logos/Warriors_United", name="Arcane_Angels"))
    expected_key = object_key("clan_logos/Warriors_United", "Arcane_Angels", data, "png")
    assert fake.puts == [{
        "Bucket": "wu-media",
        "Key": expected_key,
        "Body": data,
        "ContentType": "image/png",
        "CacheControl": CACHE_CONTROL,
    }]
    assert url == f"https://img.example.com/{expected_key}"
    assert store.key_for_url(url) == expected_key


def test_upload_bytes_sets_the_content_type_of_the_bytes_not_the_name():
    store, fake = store_with()
    asyncio.run(store.upload_bytes(image_bytes("WEBP"), folder="f", name="named_like_a_png.png"))
    assert fake.puts[0]["ContentType"] == "image/webp"
    assert fake.puts[0]["Key"].endswith(".webp")


def test_upload_rejects_empty_and_oversized_bodies():
    store, fake = store_with()
    with pytest.raises(MediaStoreError, match="empty"):
        asyncio.run(store.upload_bytes(b"", folder="f", name="n"))
    with pytest.raises(MediaStoreError, match="under 10 MB"):
        asyncio.run(store.upload_bytes(b"\0" * (MAX_IMAGE_BYTES + 1), folder="f", name="n"))
    assert fake.puts == []


def test_upload_wraps_client_failures_in_media_store_error():
    store, _ = store_with(FakeS3(fail=RuntimeError("AccessDenied")))
    with pytest.raises(MediaStoreError, match="Upload to R2 failed: AccessDenied"):
        asyncio.run(store.upload_bytes(image_bytes("PNG"), folder="f", name="n"))


def test_upload_from_url_fetches_then_uploads(monkeypatch):
    store, fake = store_with()
    seen = []

    def fake_fetch(url):
        seen.append(url)
        return image_bytes("JPEG")

    monkeypatch.setattr(media_store, "fetch_public_image", fake_fetch)
    url = asyncio.run(store.upload_from_url("https://pics.example.com/base.jpg", folder="FWA_Images/x", name="TH16_WarBase"))
    assert seen == ["https://pics.example.com/base.jpg"]
    assert fake.puts[0]["ContentType"] == "image/jpeg"
    assert url.startswith("https://img.example.com/FWA_Images/x/TH16_WarBase.")


def test_upload_from_url_reports_the_fetch_refusal(monkeypatch):
    store, fake = store_with()

    def refuse(url):
        raise ValueError("URL resolves to a non-public address.")

    monkeypatch.setattr(media_store, "fetch_public_image", refuse)
    with pytest.raises(MediaStoreError, match="non-public address"):
        asyncio.run(store.upload_from_url("http://10.0.0.1/x.png", folder="f", name="n"))
    assert fake.puts == []


# -- static art -------------------------------------------------------------

def test_object_sha256_returns_the_stored_metadata_value():
    store, fake = store_with(FakeS3(head_response={"Metadata": {"sha256": "abc123"}}))
    assert store.object_sha256("branding/logo/WU_Logo.png") == "abc123"
    assert fake.head_calls == [{"Bucket": "wu-media", "Key": "branding/logo/WU_Logo.png"}]


@pytest.mark.parametrize("code", ["404", "NoSuchKey"])
def test_object_sha256_returns_none_when_the_object_is_missing(code):
    store, _ = store_with(FakeS3(head_fail=FakeClientError(code)))
    assert store.object_sha256("branding/logo/WU_Logo.png") is None


def test_object_sha256_raises_media_store_error_for_other_failures():
    store, _ = store_with(FakeS3(head_fail=FakeClientError("AccessDenied")))
    with pytest.raises(MediaStoreError, match="Lookup in R2 failed"):
        store.object_sha256("branding/logo/WU_Logo.png")


class ResponselessError(Exception):
    """Shaped like botocore's HTTPClientError family, which sets .response
    to None (not a dict) on a transient network failure."""
    response = None


def test_object_sha256_raises_media_store_error_when_response_is_not_a_dict():
    store, _ = store_with(FakeS3(head_fail=ResponselessError("connection reset")))
    with pytest.raises(MediaStoreError, match="Lookup in R2 failed"):
        store.object_sha256("branding/logo/WU_Logo.png")


def test_object_sha256_strips_a_leading_slash_from_the_key():
    store, fake = store_with(FakeS3(head_response={"Metadata": {"sha256": "abc123"}}))
    assert store.object_sha256("/branding/logo/WU_Logo.png") == "abc123"
    assert fake.head_calls == [{"Bucket": "wu-media", "Key": "branding/logo/WU_Logo.png"}]


def test_object_sha256_raises_not_configured_when_unconfigured():
    store = MediaStore(None)
    with pytest.raises(MediaStoreNotConfigured):
        store.object_sha256("branding/logo/WU_Logo.png")


def test_upload_static_blocking_puts_a_plain_key_and_returns_its_url():
    store, fake = store_with()
    data = image_bytes("PNG")
    url = store.upload_static_blocking(data, key="branding/logo/WU_Logo.png")
    assert fake.puts == [{
        "Bucket": "wu-media",
        "Key": "branding/logo/WU_Logo.png",
        "Body": data,
        "ContentType": "image/png",
        "CacheControl": STATIC_CACHE_CONTROL,
        "Metadata": {"sha256": hashlib.sha256(data).hexdigest()},
    }]
    assert url == "https://img.example.com/branding/logo/WU_Logo.png"


def test_upload_static_blocking_rejects_a_mismatched_extension():
    store, fake = store_with()
    with pytest.raises(MediaStoreError, match="do not match its extension"):
        store.upload_static_blocking(image_bytes("PNG"), key="branding/logo/WU_Logo.jpg")
    assert fake.puts == []


def test_upload_static_blocking_accepts_jpeg_bytes_under_a_jpeg_key():
    store, fake = store_with()
    url = store.upload_static_blocking(image_bytes("JPEG"), key="fwa/static/Default_FWA_Base.jpeg")
    assert fake.puts[0]["ContentType"] == "image/jpeg"
    assert url.endswith(".jpeg")


def test_upload_static_blocking_raises_not_configured_when_unconfigured():
    store = MediaStore(None)
    with pytest.raises(MediaStoreNotConfigured):
        store.upload_static_blocking(image_bytes("PNG"), key="branding/logo/WU_Logo.png")


# -- deletes ---------------------------------------------------------------

def test_delete_url_only_touches_our_own_objects():
    store, fake = store_with()
    assert asyncio.run(store.delete_url("https://img.example.com/clan_logos/X.abc.png")) is True
    assert fake.deletes == [{"Bucket": "wu-media", "Key": "clan_logos/X.abc.png"}]
    assert asyncio.run(store.delete_url("https://res.cloudinary.com/x/image/upload/v1/X.png")) is False
    assert asyncio.run(store.delete_url(None)) is False
    assert len(fake.deletes) == 1


# -- configuration ---------------------------------------------------------

def test_unconfigured_store_fails_closed_with_a_useful_message():
    store = MediaStore(None)
    assert store.configured is False
    assert store.public_base_url is None
    with pytest.raises(MediaStoreNotConfigured, match="R2_ACCOUNT_ID"):
        asyncio.run(store.upload_bytes(image_bytes("PNG"), folder="f", name="n"))
    assert store.key_for_url("https://img.example.com/x.png") is None


def test_from_env_requires_every_variable(monkeypatch):
    values = {
        "R2_ACCOUNT_ID": "acct",
        "R2_ACCESS_KEY_ID": "key",
        "R2_SECRET_ACCESS_KEY": "secret",
        "R2_BUCKET": "wu-media",
        "R2_PUBLIC_BASE_URL": "https://img.example.com/",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    store = MediaStore.from_env()
    assert store.configured is True
    assert store.public_base_url == "https://img.example.com"

    monkeypatch.setenv("R2_BUCKET", "   ")
    assert MediaStore.from_env().configured is False
