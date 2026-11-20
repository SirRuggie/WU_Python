import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from utils.info_channel_content import (
    CLAN_TYPES,
    InfoContentUnavailable,
    about_us_defaults,
    about_us_sections,
    family_rules_sections,
    load_family_clans,
    strip_manual_clan_prefix,
    validate_rendered_text,
)
from utils.info_channel_defaults import ABOUT_US_COPY, FAMILY_RULES, WU_FAQ_QUESTIONS


COPY = json.loads((Path(__file__).parent / "fixtures/info_channels_copy.json").read_text())


def registry_rows():
    alphabet = "0289PYLQGRJCUV"
    rows = []
    for group, kind in enumerate(CLAN_TYPES):
        for number in range(1, 11):
            value, suffix = group * 10 + number, ""
            for _ in range(7):
                suffix = alphabet[value % len(alphabet)] + suffix
                value //= len(alphabet)
            rows.append({"name": f"{kind} {number:02d}", "tag": "#P" + suffix, "type": kind})
    return rows


class Clans:
    def __init__(self, rows=None, error=None):
        self.rows = rows if rows is not None else registry_rows()
        self.error = error
        self.queries = []

    def find(self, query):
        self.queries.append(query)
        return self

    async def to_list(self, *, length):
        assert length is None
        if self.error:
            raise self.error
        return self.rows


async def groups(rows=None):
    return await load_family_clans(SimpleNamespace(clans=Clans(rows)))


def test_authoritative_copy_is_exact_and_about_us_has_twelve_fields():
    assert list(FAMILY_RULES) == COPY["family_rules"]
    assert list(WU_FAQ_QUESTIONS) == COPY["wu_faq"]
    assert list(ABOUT_US_COPY) == COPY["about_us"]
    defaults = about_us_defaults()
    assert len(defaults) == 12
    assert defaults[3].startswith("**For:**")
    assert defaults[5].startswith("**For:**")
    assert defaults[7].startswith("**For:**")
    assert defaults[:3] == COPY["about_us"][:3]


def test_required_thirty_clan_fixture_is_3831_and_stored_copy_unchanged():
    async def check():
        original = copy.deepcopy(COPY["about_us"])
        rendered = about_us_sections(original, await groups())
        assert validate_rendered_text([*rendered, *family_rules_sections()]) == 3831
        assert original == COPY["about_us"]
        assert "🛡️ 10 tactical clans" in rendered[1]
        assert "🛡️ 10 Flexible Fun war clans" in rendered[1]
        assert "🛡️ 10 FWA clans for farmers" in rendered[1]
        assert rendered[3].startswith("**Tactical 01** `#P0000002`\n")
    asyncio.run(check())


def test_legacy_4161_render_is_blocked_without_rewriting_stored_data():
    async def check():
        original = copy.deepcopy(COPY["legacy_about_us_50e"])
        rendered = about_us_sections(original, await groups())
        assert sum(map(len, [*rendered, *FAMILY_RULES])) == 4161
        with pytest.raises(ValueError, match="4,161 characters.*4,000"):
            validate_rendered_text([*rendered, *FAMILY_RULES])
        assert original == COPY["legacy_about_us_50e"]
    asyncio.run(check())


def test_long_registry_names_use_real_rendered_budget_not_fixture_headroom():
    async def check():
        rows = registry_rows()
        for row in rows:
            row["name"] += " longer clan name"
        rendered = about_us_sections(about_us_defaults(), await groups(rows))
        with pytest.raises(ValueError, match="No post was changed"):
            validate_rendered_text([*rendered, *FAMILY_RULES])
    asyncio.run(check())


def test_one_query_filters_and_sorts_without_mutating_registry_rows():
    async def check():
        rows = list(reversed(registry_rows()))
        rows += [
            {"name": "CWL", "tag": "#PPPPPPP", "type": "CWL"},
            {"name": "Archived", "tag": "#PYYYYYY", "type": "Tactical", "archived": True},
            {"name": "Removed", "tag": "#PQQQQQQ", "type": "FWA", "removed": True},
        ]
        before = copy.deepcopy(rows)
        collection = Clans(rows)
        selected = await load_family_clans(SimpleNamespace(clans=collection))
        assert collection.queries == [{
            "type": {"$in": ["Tactical", "Flexible Fun", "FWA"]},
            "archived": {"$ne": True},
            "removed": {"$ne": True},
        }]
        assert {kind: len(value) for kind, value in selected.items()} == dict.fromkeys(CLAN_TYPES, 10)
        assert selected["Tactical"][0]["name"] == "Tactical 01"
        assert selected["FWA"][-1]["name"] == "FWA 10"
        assert rows == before
    asyncio.run(check())


def test_registry_unavailable_does_not_become_empty_public_lists():
    async def check():
        db = SimpleNamespace(clans=Clans(error=ServerSelectionTimeoutError("private details")))
        with pytest.raises(InfoContentUnavailable, match="cannot read the clan registry") as raised:
            await load_family_clans(db)
        assert "private details" not in str(raised.value)
    asyncio.run(check())


@pytest.mark.parametrize("change", ["missing_name", "invalid_tag", "duplicate", "missing_type"])
def test_bad_or_missing_active_clan_data_fails_visibly(change):
    async def check():
        rows = registry_rows()
        if change == "missing_name":
            rows[0].pop("name")
        elif change == "invalid_tag":
            rows[0]["tag"] = "#INVALID"
        elif change == "duplicate":
            rows.append(dict(rows[0]))
        else:
            rows = [row for row in rows if row["type"] != "FWA"]
        with pytest.raises(InfoContentUnavailable):
            await groups(rows)
    asyncio.run(check())


def test_prefix_migration_preserves_nonprefix_manual_looking_description():
    text = "**Old Clan (#P0YQ8)**\n**Second Clan** `#P0YQ9`\n\nDescription.\n**Example** `#P0YQ8`"
    assert strip_manual_clan_prefix(text) == "\nDescription.\n**Example** `#P0YQ8`"
    assert strip_manual_clan_prefix("Description.\n**Example** `#P0YQ8`") == "Description.\n**Example** `#P0YQ8`"


def test_registry_markdown_is_escaped_and_same_count_is_used():
    async def check():
        rows = registry_rows()
        rows[0]["name"] = "A **bold** [link]"
        rendered = about_us_sections(about_us_defaults(), await groups(rows))
        assert r"**A \*\*bold\*\* \[link\]**" in rendered[3]
        assert "10 tactical clans" in rendered[1]
    asyncio.run(check())


def test_budget_boundaries_include_derived_text():
    assert validate_rendered_text(["a" * 3000, "b" * 1000]) == 4000
    with pytest.raises(ValueError, match="4,001"):
        validate_rendered_text(["a" * 3000, "b" * 1001])
