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
    MediaStore,
    MediaStoreConfig,
    MediaStoreError,
    MediaStoreNotConfigured,
    detect_image,
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


class FakeS3:
    def __init__(self, fail=None):
        self.puts = []
        self.deletes = []
        self.fail = fail

    def put_object(self, **kwargs):
        if self.fail:
            raise self.fail
        self.puts.append(kwargs)

    def delete_object(self, **kwargs):
        if self.fail:
            raise self.fail
        self.deletes.append(kwargs)


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
