import asyncio

from tools import import_fwa_blacklist as importer

SAMPLE_MD = """# Blacklisted clans — ChocolateClash

Retrieved: 2026-09-08

Source: https://cc.fwafarm.com/cc_n/clanlist.php?filter=0

Scope: All entries returned by the site's BL filter.

Total: 4 clans.

## Category counts

| Site classification | Count |
| --- | ---: |
| FWA Blacklisted | 3 |
| OL China Blacklisted | 1 |

## Clan list

| Clan name | Clan tag | Site classification | Source |
| --- | --- | --- | --- |
| "Monkey Baby" | `#8YGLCPCL` | FWA Blacklisted | [View](https://cc.fwafarm.com/cc_n/clan.php?tag=8YGLCPCL) |
| ✨梦✨ | `#J22U` | FWA Blacklisted | [View](https://cc.fwafarm.com/cc_n/clan.php?tag=J22U) |
| ⭐ARZ GROUP⭐ | `#VUQULPGY` | OL China Blacklisted | [View](https://cc.fwafarm.com/cc_n/clan.php?tag=VUQULPGY) |
| Malformed Row | #NOBACKTICKS | FWA Blacklisted | View |
"""


# ---------------------------------------------------------------------------
# parse_markdown
# ---------------------------------------------------------------------------

def test_parse_markdown_reads_header_and_rows():
    result = importer.parse_markdown(SAMPLE_MD)

    assert result.retrieved == "2026-09-08"
    assert result.source == "https://cc.fwafarm.com/cc_n/clanlist.php?filter=0"
    assert len(result.rows) == 3
    assert result.unparsed == 1


def test_parse_markdown_handles_quoted_and_unicode_names():
    result = importer.parse_markdown(SAMPLE_MD)
    by_tag = {row["tag"]: row for row in result.rows}

    assert by_tag["8YGLCPCL"]["name"] == '"Monkey Baby"'
    assert by_tag["8YGLCPCL"]["classification"] == "FWA Blacklisted"
    assert by_tag["J22U"]["name"] == "✨梦✨"
    assert by_tag["VUQULPGY"]["classification"] == "OL China Blacklisted"


def test_parse_markdown_ignores_category_counts_table():
    # "| FWA Blacklisted | 3 |" (no backtick tag) must not be mistaken for a
    # data row or counted as unparsed -- it is outside "## Clan list".
    result = importer.parse_markdown(SAMPLE_MD)
    assert result.unparsed == 1


# ---------------------------------------------------------------------------
# --only-fwa filtering
# ---------------------------------------------------------------------------

def test_only_fwa_filters_to_exact_classification():
    result = importer.parse_markdown(SAMPLE_MD)
    fwa_only = [
        row for row in result.rows
        if row["classification"] == importer.ONLY_FWA_CLASSIFICATION
    ]
    assert {row["tag"] for row in fwa_only} == {"8YGLCPCL", "J22U"}


def test_main_only_fwa_flag_filters_rows(tmp_path, monkeypatch):
    md_path = tmp_path / "blacklisted-clans.md"
    md_path.write_text(SAMPLE_MD, encoding="utf-8")

    captured = {}

    async def fake_run(uri, rows, *, dry_run, source_url, retrieved_at):
        captured["rows"] = rows
        return (0, 0, {})

    monkeypatch.setenv("MONGODB_URI", "mongodb://fake")
    monkeypatch.setattr(importer, "_run", fake_run)

    rc = importer.main([str(md_path), "--only-fwa", "--dry-run"])

    assert rc == 0
    assert {row["tag"] for row in captured["rows"]} == {"8YGLCPCL", "J22U"}


# ---------------------------------------------------------------------------
# write path -- fake collection, same style as tests/test_fwa_blacklist.py
# ---------------------------------------------------------------------------

class _UpdateResult:
    pass


class _FindResult:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    """Fake mongo.fwa_blacklist keyed by _id, close enough to real Mongo
    semantics for $set / $setOnInsert / $in to be exercised here."""

    def __init__(self, docs=None):
        self.docs = {doc["_id"]: dict(doc) for doc in (docs or [])}
        self.set_calls = []

    async def find_one(self, query):
        return self.docs.get(query["_id"])

    async def update_one(self, query, update, upsert=False):
        _id = query["_id"]
        if "$set" in update:
            self.set_calls.append((_id, dict(update["$set"])))
        existing = self.docs.get(_id)
        if existing is None:
            if not upsert:
                return _UpdateResult()
            doc = {"_id": _id}
            doc.update(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            self.docs[_id] = doc
        else:
            existing.update(update.get("$set", {}))
        return _UpdateResult()

    def find(self, query=None, projection=None):
        query = query or {}
        if "_id" in query and "$in" in query["_id"]:
            wanted = set(query["_id"]["$in"])
            return _FindResult([doc for _id, doc in self.docs.items() if _id in wanted])
        return _FindResult(list(self.docs.values()))


class _Mongo:
    def __init__(self, collection):
        self.fwa_blacklist = collection


def test_import_rows_sets_classification_and_uses_import_source():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    rows = [{"name": "Monkey Baby", "tag": "#8YGLCPCL", "classification": "FWA Blacklisted"}]

    inserted, updated, per_classification = asyncio.run(
        importer.import_rows(
            mongo, rows,
            dry_run=False,
            source_url="https://example.com/export",
            retrieved_at="2026-09-08",
        )
    )

    assert inserted == 1
    assert updated == 0
    assert per_classification == {"FWA Blacklisted": 1}

    doc = collection.docs["8YGLCPCL"]
    assert doc["source"] == "import"
    assert doc["added_by_id"] == 0
    assert doc["added_by_name"] == "import"
    assert doc["classification"] == "FWA Blacklisted"
    assert doc["imported_from"] == "https://example.com/export"
    assert doc["retrieved_at"] == "2026-09-08"

    # classification was written via $set on an update_one call.
    assert any(fields.get("classification") == "FWA Blacklisted" for _id, fields in collection.set_calls)


def test_import_rows_never_overwrites_existing_source_or_added_by():
    collection = _FakeCollection([{
        "_id": "8YGLCPCL",
        "name": "Monkey Baby",
        "added_at": "2020-01-01T00:00:00+00:00",
        "added_by_id": 555,
        "added_by_name": "SomeStaffer",
        "source": "war-plans",
    }])
    mongo = _Mongo(collection)
    rows = [{"name": "Monkey Baby", "tag": "#8YGLCPCL", "classification": "FWA Blacklisted"}]

    inserted, updated, _ = asyncio.run(
        importer.import_rows(
            mongo, rows, dry_run=False, source_url="https://example.com", retrieved_at="2026-09-08",
        )
    )

    assert inserted == 0
    assert updated == 1
    doc = collection.docs["8YGLCPCL"]
    assert doc["source"] == "war-plans"
    assert doc["added_by_id"] == 555
    assert doc["added_by_name"] == "SomeStaffer"
    assert doc["classification"] == "FWA Blacklisted"


def test_import_rows_dry_run_writes_nothing():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    rows = [{"name": "Monkey Baby", "tag": "#8YGLCPCL", "classification": "FWA Blacklisted"}]

    inserted, updated, per_classification = asyncio.run(
        importer.import_rows(
            mongo, rows, dry_run=True, source_url="https://example.com", retrieved_at="2026-09-08",
        )
    )

    assert inserted == 1
    assert updated == 0
    assert per_classification == {"FWA Blacklisted": 1}
    assert collection.docs == {}
