"""Saved message colors move to the brand colors without overwriting later edits."""

import asyncio
import copy
import json
from types import SimpleNamespace

from tools import migrate_brand_accents as migration
from utils import declaration_pings
from utils.constants import WU_GOLD, WU_GREEN, WU_RED


def test_script_colors_match_brand_constants():
    from extensions.commands.fwa.message_templates import WAR_COLORS

    assert (migration.WU_GOLD, migration.WU_GREEN, migration.WU_RED) == (int(WU_GOLD), int(WU_GREEN), int(WU_RED))
    assert migration.WAR_DEFAULTS == {key: int(value) for key, value in WAR_COLORS.items()}


class FakeCollection:
    def __init__(self, documents):
        self.documents = {doc["_id"]: copy.deepcopy(doc) for doc in documents}
        self.before_write = None

    def find(self, query):
        documents = [copy.deepcopy(doc) for doc in self.documents.values()]
        return SimpleNamespace(to_list=lambda length=None: _done(documents))

    @staticmethod
    def _get(doc, path):
        for part in path.split("."):
            doc = doc[int(part)] if isinstance(doc, list) else doc.get(part)
        return doc

    @staticmethod
    def _set(doc, path, value):
        parts = path.split(".")
        for part in parts[:-1]:
            doc = doc[int(part)] if isinstance(doc, list) else doc[part]
        doc[parts[-1]] = value

    async def update_one(self, query, update):
        if self.before_write:
            self.before_write(self.documents)
            self.before_write = None
        doc = self.documents.get(query["_id"])
        if doc is None or any(self._get(doc, k) != v for k, v in query.items() if k != "_id"):
            return SimpleNamespace(modified_count=0)
        for path, value in update.get("$set", {}).items():
            self._set(doc, path, value)
        for path, value in update.get("$inc", {}).items():
            doc[path] = doc.get(path, 0) + value
        return SimpleNamespace(modified_count=1)


async def _done(value):
    return value


def _rows():
    return [
        {"_id": "fwa_war_template:1:win", "accent": 0x00B237, "revision": 2},
        {"_id": "fwa_war_template:1:lose", "accent": 0xAA0000, "revision": 1},
        {"_id": "fwa_war_template:1:mismatch", "accent": 0xFFD700, "revision": 0},
        {"_id": "fwa_war_template:1:blacklisted", "accent": 0x000000, "revision": 3},
        {"_id": "recruit_question_template:1:family_codes", "accent": 0xEEEEAA, "revision": 4},
        {"_id": "recruit_question_template:1:circles", "accent": 0xAA0000, "revision": 1},
        {"_id": "recruit_question_template:1:today", "accent": 0x123456, "revision": 1},
        {"_id": "cwl:cycle:1:2026-12", "revision": 7, "campaign": {"messages": {"signup": {"accent_color": 0x0066FF}}},
         "revisions": [{"campaign": {"messages": {"signup": {"accent_color": 0x0066FF}}}}]},
        {"_id": "other:1", "accent": 0xAA0000},
    ]


def _run(collection, **kwargs):
    lines = []
    code = asyncio.run(migration.run(collection, out=lines.append, **kwargs))
    return code, lines


def test_dry_run_lists_changes_and_writes_nothing():
    collection = FakeCollection(_rows())
    before = copy.deepcopy(collection.documents)
    code, lines = _run(collection, apply=False, backup=None)
    assert code == 0 and collection.documents == before
    changes = [line for line in lines if line.startswith("CHANGE")]
    assert "CHANGE fwa_war_template:1:lose accent: #AA0000 -> #E00010" in changes
    assert "CHANGE recruit_question_template:1:circles accent: #AA0000 -> #F2B62A" in changes
    assert "CHANGE cwl:cycle:1:2026-12 campaign.messages.signup.accent_color: #0066FF -> #F2B62A" in changes
    assert "CHANGE recruit_question_template:1:today accent: #123456 -> #F2B62A" in changes
    assert len(changes) == 7
    assert "KEEP   fwa_war_template:1:blacklisted accent: #000000" in lines
    assert lines[-1] == "DRY RUN: nothing written"


def test_apply_moves_every_color_to_its_default_and_keeps_history(tmp_path):
    collection = FakeCollection(_rows())
    backup = tmp_path / "backup.json"
    code, _lines = _run(collection, apply=True, backup=backup)
    docs = collection.documents
    assert code == 0
    assert (docs["fwa_war_template:1:win"]["accent"], docs["fwa_war_template:1:win"]["revision"]) == (0x00D659, 3)
    assert docs["fwa_war_template:1:lose"]["accent"] == 0xE00010
    assert docs["fwa_war_template:1:mismatch"]["accent"] == 0xF2B62A
    assert docs["fwa_war_template:1:blacklisted"] == _rows()[3]
    assert docs["recruit_question_template:1:family_codes"]["accent"] == 0xF2B62A
    assert docs["recruit_question_template:1:circles"]["accent"] == 0xF2B62A
    assert docs["recruit_question_template:1:today"]["accent"] == 0xF2B62A
    cycle = docs["cwl:cycle:1:2026-12"]
    assert cycle["campaign"]["messages"]["signup"]["accent_color"] == 0xF2B62A
    assert cycle["revision"] == 7
    assert cycle["revisions"][0]["campaign"]["messages"]["signup"]["accent_color"] == 0x0066FF
    assert docs["other:1"]["accent"] == 0xAA0000
    assert len(json.loads(backup.read_text(encoding="utf-8"))) == len(_rows())


def test_apply_skips_a_document_edited_after_the_read(tmp_path):
    collection = FakeCollection(_rows()[:2])

    def staff_edit(documents):
        documents["fwa_war_template:1:win"].update(accent=0x00B237, revision=3)

    collection.before_write = staff_edit
    code, lines = _run(collection, apply=True, backup=tmp_path / "b.json")
    assert code == 1
    assert collection.documents["fwa_war_template:1:win"]["revision"] == 3
    assert collection.documents["fwa_war_template:1:win"]["accent"] == 0x00B237
    assert any(line.startswith("SKIPPED fwa_war_template:1:win") for line in lines)
    assert collection.documents["fwa_war_template:1:lose"]["accent"] == 0xE00010


def test_apply_without_backup_writes_nothing():
    collection = FakeCollection(_rows())
    before = copy.deepcopy(collection.documents)
    code, _lines = _run(collection, apply=True, backup=None)
    assert code == 2 and collection.documents == before


def test_cli_refuses_apply_without_backup_and_existing_backup(tmp_path, capsys):
    assert migration.main(["--apply"]) == 2
    existing = tmp_path / "exists.json"
    existing.write_text("[]", encoding="utf-8")
    assert migration.main(["--apply", "--backup", str(existing)]) == 2


def test_declaration_ping_uses_wu_gold():
    group = {"tag": "#2PP", "name": "Clan", "users": [123456789012345678], "unlinked": [], "accounts": [{"tag": "#9", "user_id": 1}]}
    payload = declaration_pings.messages([group], test=True)[0]
    assert payload["components"][0]["accent_color"] == int(WU_GOLD)
