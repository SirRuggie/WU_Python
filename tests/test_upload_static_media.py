"""tools/upload_static_media.py against a fake repo tree and a fake MediaStore.

Never touches the network or real environment variables: `main()` is driven
by monkeypatching the module's store factory and repo-root function.
"""

import hashlib
import shutil
from io import BytesIO

import pytest
from PIL import Image

from tests.test_media_store import FakeClientError, FakeS3
from tools import upload_static_media as usm
from utils.media_store import MediaStore, MediaStoreConfig

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


def build_fake_repo(tmp_path):
    """The fixture tree described in the spec, five real static images plus
    three files that must be excluded or skipped."""
    files = {
        "assets/branding/logo/a.png": image_bytes("PNG"),
        "assets/branding/banners/b.gif": image_bytes("GIF"),
        "assets/fwa/static/c.jpg": image_bytes("JPEG"),
        "assets/recruit/strikes/d.png": image_bytes("PNG", (0, 255, 0)),
        "assets/tickets/static/e.png": image_bytes("PNG", (0, 0, 255)),
        # must be excluded: not a static root
        "assets/cards/x.webp": image_bytes("WEBP"),
        # must be excluded: a footer, sits directly under assets/
        "assets/Blue_Footer.png": image_bytes("PNG"),
        # must be skipped: not an image
        "assets/branding/notes.txt": b"not an image",
        # must be excluded: hidden directory
        "assets/branding/.cache/x.png": image_bytes("PNG"),
    }
    for rel, data in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return tmp_path


EXPECTED_KEYS = [
    "branding/banners/b.gif",
    "branding/logo/a.png",
    "fwa/static/c.jpg",
    "recruit/strikes/d.png",
    "tickets/static/e.png",
]


# -- iter_static_files -------------------------------------------------------

def test_iter_static_files_returns_exactly_the_five_keys_sorted(tmp_path):
    build_fake_repo(tmp_path)
    pairs = usm.iter_static_files(tmp_path)
    assert [key for _, key in pairs] == EXPECTED_KEYS
    for path, key in pairs:
        assert path.is_file()
        assert "\\" not in key   # POSIX separators, even were this run on Windows


def test_iter_static_files_excludes_hidden_directories(tmp_path):
    build_fake_repo(tmp_path)
    pairs = usm.iter_static_files(tmp_path)
    assert not any(".cache" in key for _, key in pairs)


# -- sync_file ----------------------------------------------------------------

def test_sync_uploads_a_missing_object_under_the_right_key(tmp_path):
    build_fake_repo(tmp_path)
    fake = FakeS3(head_fail=FakeClientError("404"))
    store = MediaStore(CONFIG, client=fake)
    tally = usm.Tally()
    path = tmp_path / "assets/branding/logo/a.png"

    result = usm.sync_file(store, path, "branding/logo/a.png", dry_run=False, tally=tally)

    assert result == "uploaded"
    assert tally.uploaded == 1
    assert fake.puts[0]["Key"] == "branding/logo/a.png"
    assert fake.puts[0]["ContentType"] == "image/png"


def test_sync_skips_when_remote_sha256_matches_local(tmp_path):
    build_fake_repo(tmp_path)
    path = tmp_path / "assets/branding/logo/a.png"
    local = hashlib.sha256(path.read_bytes()).hexdigest()
    fake = FakeS3(head_response={"Metadata": {"sha256": local}})
    store = MediaStore(CONFIG, client=fake)
    tally = usm.Tally()

    result = usm.sync_file(store, path, "branding/logo/a.png", dry_run=False, tally=tally)

    assert result == "unchanged"
    assert tally.unchanged == 1
    assert fake.puts == []


def test_sync_uploads_when_remote_sha256_differs(tmp_path):
    build_fake_repo(tmp_path)
    path = tmp_path / "assets/branding/logo/a.png"
    fake = FakeS3(head_response={"Metadata": {"sha256": "stale"}})
    store = MediaStore(CONFIG, client=fake)
    tally = usm.Tally()

    result = usm.sync_file(store, path, "branding/logo/a.png", dry_run=False, tally=tally)

    assert result == "uploaded"
    assert tally.uploaded == 1
    assert len(fake.puts) == 1


def test_sync_dry_run_makes_no_put_object_calls_but_counts(tmp_path):
    build_fake_repo(tmp_path)
    path = tmp_path / "assets/branding/logo/a.png"
    fake = FakeS3(head_fail=FakeClientError("404"))
    store = MediaStore(CONFIG, client=fake)
    tally = usm.Tally()

    result = usm.sync_file(store, path, "branding/logo/a.png", dry_run=True, tally=tally)

    assert result == "would upload"
    assert tally.uploaded == 1
    assert fake.puts == []


def test_sync_dry_run_and_real_agree_on_a_corrupt_file(tmp_path):
    build_fake_repo(tmp_path)
    bad = tmp_path / "assets/branding/logo/bad.png"
    bad.write_bytes(b"not an image")
    fake = FakeS3(head_fail=FakeClientError("404"))
    store = MediaStore(CONFIG, client=fake)

    dry_tally = usm.Tally()
    dry_result = usm.sync_file(store, bad, "branding/logo/bad.png", dry_run=True, tally=dry_tally)
    assert dry_result == "failed"
    assert dry_tally.failed == 1

    real_tally = usm.Tally()
    real_result = usm.sync_file(store, bad, "branding/logo/bad.png", dry_run=False, tally=real_tally)
    assert real_result == "failed"
    assert real_tally.failed == 1
    assert fake.puts == []


def test_sync_isolates_a_failure_and_others_still_upload(tmp_path):
    build_fake_repo(tmp_path)

    class FailOnceS3(FakeS3):
        def put_object(self, **kwargs):
            if kwargs["Key"] == "branding/logo/a.png":
                raise RuntimeError("AccessDenied")
            super().put_object(**kwargs)

        def head_object(self, **kwargs):
            raise FakeClientError("404")

    fake = FailOnceS3()
    store = MediaStore(CONFIG, client=fake)
    tally = usm.Tally()

    for path, key in usm.iter_static_files(tmp_path):
        usm.sync_file(store, path, key, dry_run=False, tally=tally)

    assert tally.failed == 1
    assert tally.uploaded == 4
    assert len(fake.puts) == 4


# -- main ----------------------------------------------------------------------

def test_main_returns_1_when_a_file_fails(tmp_path, monkeypatch):
    build_fake_repo(tmp_path)

    class FailOnceS3(FakeS3):
        def put_object(self, **kwargs):
            if kwargs["Key"] == "branding/logo/a.png":
                raise RuntimeError("AccessDenied")
            super().put_object(**kwargs)

        def head_object(self, **kwargs):
            raise FakeClientError("404")

    fake = FailOnceS3()
    store = MediaStore(CONFIG, client=fake)
    monkeypatch.setattr(usm, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(usm, "default_store", lambda: store)

    assert usm.main([]) == 1


def test_main_returns_2_when_unconfigured_and_not_dry_run(tmp_path, monkeypatch):
    build_fake_repo(tmp_path)
    monkeypatch.setattr(usm, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(usm, "default_store", lambda: MediaStore(None))

    assert usm.main([]) == 2


def test_main_dry_run_with_no_config_lists_every_file_and_returns_0(tmp_path, monkeypatch, capsys):
    build_fake_repo(tmp_path)
    monkeypatch.setattr(usm, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(usm, "default_store", lambda: MediaStore(None))

    assert usm.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    for key in EXPECTED_KEYS:
        assert key in out
    assert "uploaded=5" in out or "would upload=5" in out


def test_main_missing_root_is_tallied_as_a_failure(tmp_path, monkeypatch, capsys):
    build_fake_repo(tmp_path)
    shutil.rmtree(tmp_path / "assets" / "tickets")
    monkeypatch.setattr(usm, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(usm, "default_store", lambda: MediaStore(None))

    assert usm.main(["--dry-run"]) == 1
    out = capsys.readouterr().out
    assert "missing root" in out
