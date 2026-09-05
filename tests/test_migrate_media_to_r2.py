"""tools/migrate_media_to_r2.py against a stub Mongo handle and a fake S3
client.

Pins two things: the bucket-key layout the script commits Mongo to
(`clans/<Name>/logo` and `banner`, `fwa/bases/<th>/war` and `active`, with
the content hash appended), and the `is_cloudinary` host check that keeps an
internal-address value like the dashboard's IMG_RE can produce from ever
being fetched.
"""

import re

import pytest

from tests.test_media_store import CONFIG, FakeS3, image_bytes
from tools import migrate_media_to_r2 as mig
from utils.media_store import MediaStore

CLOUDINARY_A = "https://res.cloudinary.com/dxmtzuomk/image/upload/v1/a.png"
CLOUDINARY_B = "https://res.cloudinary.com/dxmtzuomk/image/upload/v1/b.png"
CLOUDINARY_C = "https://res.cloudinary.com/dxmtzuomk/image/upload/v1/c.png"
INTERNAL_URL = "http://127.0.0.1:9200/res.cloudinary.com/a.png"
R2_URL = "https://wu-media.ruggie.zone/clans/X/logo.abc.png"

HASH_RE = "[0-9a-f]{10}"


class FakeCollection:
    def __init__(self, find_docs=None, find_one_doc=None):
        self._find_docs = find_docs if find_docs is not None else []
        self._find_one_doc = find_one_doc
        self.updates = []
        self.find_queries = []

    def find(self, query, projection):
        self.find_queries.append(query)
        return self._find_docs

    def find_one(self, query):
        return self._find_one_doc

    def update_one(self, filter, update):
        self.updates.append((filter, update))


class FakeDB:
    def __init__(self, clan_docs=None, fwa_doc=None):
        self.clan_data = FakeCollection(find_docs=clan_docs)
        self.fwa_data = FakeCollection(find_one_doc=fwa_doc)


@pytest.fixture
def store_and_fake():
    fake = FakeS3()
    return MediaStore(CONFIG, client=fake), fake


@pytest.fixture(autouse=True)
def default_download(monkeypatch):
    monkeypatch.setattr(mig, "download_image_blocking", lambda url: image_bytes("PNG"))


# -- is_cloudinary ------------------------------------------------------------

@pytest.mark.parametrize(("value", "expected"), [
    ("https://res.cloudinary.com/dxmtzuomk/image/upload/v1/x.png", True),
    ("https://RES.CLOUDINARY.COM/dxmtzuomk/image/upload/v1/x.png", True),
    ("http://127.0.0.1:9200/res.cloudinary.com/a.png", False),
    ("https://wu-media.ruggie.zone/clans/X/logo.abc.png", False),
    ("https://[res.cloudinary.com/x.png", False),
    (None, False),
    (12345, False),
])
def test_is_cloudinary(value, expected):
    assert mig.is_cloudinary(value) is expected


# -- migrate_clans --------------------------------------------------------------

def test_migrate_clans_query_is_case_insensitive_and_escapes_the_host(store_and_fake):
    store, fake = store_and_fake
    db = FakeDB(clan_docs=[])
    tally = mig.Tally()

    mig.migrate_clans(db, store, dry_run=False, tally=tally)

    assert len(db.clan_data.find_queries) == 1
    clauses = db.clan_data.find_queries[0]["$or"]
    assert len(clauses) == 2
    for field, clause in zip(("logo", "banner"), clauses):
        assert clause[field]["$options"] == "i"
        assert clause[field]["$regex"] == re.escape("res.cloudinary.com")


def test_migrate_clans_uploads_under_the_agreed_bucket_layout(store_and_fake):
    store, fake = store_and_fake
    doc = {"_id": 1, "tag": "#ABC", "name": "Arcane Angels",
           "logo": CLOUDINARY_A, "banner": CLOUDINARY_B}
    db = FakeDB(clan_docs=[doc])
    tally = mig.Tally()

    mig.migrate_clans(db, store, dry_run=False, tally=tally)

    logo_puts = [p for p in fake.puts if "/logo." in p["Key"]]
    banner_puts = [p for p in fake.puts if "/banner." in p["Key"]]
    assert len(logo_puts) == 1
    assert len(banner_puts) == 1
    assert re.fullmatch(rf"clans/Arcane_Angels/logo\.{HASH_RE}\.png", logo_puts[0]["Key"])
    assert re.fullmatch(rf"clans/Arcane_Angels/banner\.{HASH_RE}\.png", banner_puts[0]["Key"])
    assert tally.migrated == 2

    assert len(db.clan_data.updates) == 2
    sets = {}
    for filt, update in db.clan_data.updates:
        assert filt == {"_id": 1}
        sets.update(update["$set"])
    assert sets["logo"] == store.public_url(logo_puts[0]["Key"])
    assert sets["banner"] == store.public_url(banner_puts[0]["Key"])


def test_migrate_clans_uses_the_tag_folder_when_name_is_missing(store_and_fake):
    store, fake = store_and_fake
    doc = {"_id": 2, "tag": "#DEF", "logo": CLOUDINARY_A, "banner": CLOUDINARY_B}
    db = FakeDB(clan_docs=[doc])
    tally = mig.Tally()

    mig.migrate_clans(db, store, dry_run=False, tally=tally)

    assert all(p["Key"].startswith("clans/DEF/") for p in fake.puts)
    assert tally.migrated == 2


def test_migrate_clans_skips_a_value_already_on_r2(store_and_fake):
    store, fake = store_and_fake
    doc = {"_id": 3, "tag": "#GHI", "name": "Some Clan", "logo": R2_URL, "banner": None}
    db = FakeDB(clan_docs=[doc])
    tally = mig.Tally()

    mig.migrate_clans(db, store, dry_run=False, tally=tally)

    assert fake.puts == []
    assert db.clan_data.updates == []
    assert tally.migrated == 0
    assert tally.skipped == 2   # logo already on R2, banner is None


def test_migrate_clans_skips_an_internal_address_without_downloading(store_and_fake, monkeypatch):
    store, fake = store_and_fake
    doc = {"_id": 4, "tag": "#JKL", "name": "Sneaky Clan", "logo": INTERNAL_URL, "banner": None}
    db = FakeDB(clan_docs=[doc])
    tally = mig.Tally()

    def fail_if_called(url):
        pytest.fail(f"download_image_blocking should not be called for {url}")

    monkeypatch.setattr(mig, "download_image_blocking", fail_if_called)

    mig.migrate_clans(db, store, dry_run=False, tally=tally)

    assert fake.puts == []
    assert db.clan_data.updates == []
    assert tally.migrated == 0
    assert tally.skipped == 2


def test_migrate_clans_isolates_a_download_failure(store_and_fake, monkeypatch):
    store, fake = store_and_fake
    clan1 = {"_id": 1, "tag": "#ABC", "name": "Clan One", "logo": CLOUDINARY_A, "banner": CLOUDINARY_B}
    clan2 = {"_id": 2, "tag": "#DEF", "name": "Clan Two", "logo": CLOUDINARY_A, "banner": CLOUDINARY_B}
    db = FakeDB(clan_docs=[clan1, clan2])
    tally = mig.Tally()

    calls = {"n": 0}

    def flaky_download(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection reset")
        return image_bytes("PNG")

    monkeypatch.setattr(mig, "download_image_blocking", flaky_download)

    mig.migrate_clans(db, store, dry_run=False, tally=tally)

    assert tally.failed == 1
    assert tally.migrated == 3

    updated_fields = set()
    for filt, update in db.clan_data.updates:
        for field in update["$set"]:
            updated_fields.add((filt["_id"], field))

    assert (1, "logo") not in updated_fields
    assert (1, "banner") in updated_fields
    assert (2, "logo") in updated_fields
    assert (2, "banner") in updated_fields


def test_migrate_clans_dry_run_makes_no_writes(store_and_fake):
    store, fake = store_and_fake
    doc = {"_id": 1, "tag": "#ABC", "name": "Arcane Angels",
           "logo": CLOUDINARY_A, "banner": CLOUDINARY_B}
    db = FakeDB(clan_docs=[doc])
    tally = mig.Tally()

    mig.migrate_clans(db, store, dry_run=True, tally=tally)

    assert fake.puts == []
    assert db.clan_data.updates == []
    assert tally.migrated == 0
    assert tally.failed == 0
    assert tally.skipped == 0


# -- migrate_fwa ------------------------------------------------------------

def test_migrate_fwa_uploads_under_the_agreed_bucket_layout(store_and_fake):
    store, fake = store_and_fake
    fwa_doc = {
        "_id": "fwa_config",
        "war_base_images": {"th16": CLOUDINARY_A, "th16_new": CLOUDINARY_B},
        "active_base_images": {"th9": CLOUDINARY_C},
    }
    db = FakeDB(fwa_doc=fwa_doc)
    tally = mig.Tally()

    mig.migrate_fwa(db, store, dry_run=False, tally=tally)

    def find_key(prefix):
        matches = [p["Key"] for p in fake.puts if p["Key"].startswith(prefix)]
        assert len(matches) == 1
        return matches[0]

    th16_war = find_key("fwa/bases/th16/war.")
    th16_new_war = find_key("fwa/bases/th16_new/war.")
    th9_active = find_key("fwa/bases/th9/active.")

    assert re.fullmatch(rf"fwa/bases/th16/war\.{HASH_RE}\.png", th16_war)
    assert re.fullmatch(rf"fwa/bases/th16_new/war\.{HASH_RE}\.png", th16_new_war)
    assert re.fullmatch(rf"fwa/bases/th9/active\.{HASH_RE}\.png", th9_active)
    assert tally.migrated == 3

    sets = {}
    for filt, update in db.fwa_data.updates:
        assert filt == {"_id": "fwa_config"}
        sets.update(update["$set"])
    assert set(sets) == {
        "war_base_images.th16", "war_base_images.th16_new", "active_base_images.th9",
    }


def test_migrate_fwa_dry_run_makes_no_writes(store_and_fake):
    store, fake = store_and_fake
    fwa_doc = {
        "_id": "fwa_config",
        "war_base_images": {"th16": CLOUDINARY_A},
        "active_base_images": {"th9": CLOUDINARY_C},
    }
    db = FakeDB(fwa_doc=fwa_doc)
    tally = mig.Tally()

    mig.migrate_fwa(db, store, dry_run=True, tally=tally)

    assert fake.puts == []
    assert db.fwa_data.updates == []
    assert tally.migrated == 0
    assert tally.failed == 0
    assert tally.skipped == 0
