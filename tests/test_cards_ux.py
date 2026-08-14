"""Structural pins for the Cards UX redesign.

These tests hold the redesign's shape, not its exact prose: one main
Container per screen, the compact-callout ladder for FWA and Noahs Ark, slim
status DMs that name only the reader's account, no decorative footer image,
and no trace of the removed freshness-confirmation concept anywhere in the
rendered UI.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari

from extensions.commands import cards as cards_command
from extensions.commands import cards_preview
from utils import cards
from utils.constants import BLUE_ACCENT
from utils.todo_data import Account


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _payload(view):
    return [component.build() for component in view]


def _built(component):
    """The raw payload dict from a builder's build() result.

    On this hikari, a container's build() returns (payload, attachments).
    """
    built = component.build()
    return built[0] if isinstance(built, tuple) else built


def _nodes(view):
    return list(_walk(_payload(view)))


def _text(view):
    return "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )


def _labels(view):
    return [
        str(node["label"])
        for node in _nodes(view)
        if node.get("type") == 2 and "label" in node
    ]


def _custom_ids(view):
    return [
        str(node["custom_id"]) for node in _nodes(view) if "custom_id" in node
    ]


def _account():
    return Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=17,
    )


def _trade(**overrides):
    base = {
        "_id": "ux-trade",
        "kind": "trade",
        "guild_id": 1,
        "status": "move_needed",
        "wanted_card_id": "meteor_golem",
        "given_card_id": "electro_titan",
        "compatible_card_ids": [],
        "requester_tag": "#REQ",
        "requester_name": "Requester",
        "requester_discord_id": 111,
        "requester_clan_tag": "#HOME",
        "requester_clan_name": "Home Clan",
        "requester_town_hall": 17,
        "holder_tag": "#HOLD",
        "holder_name": "Holder",
        "holder_discord_id": 222,
        "holder_clan_tag": "#AWAY",
        "holder_clan_name": "Away Clan",
        "holder_town_hall": 18,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


FRESHNESS_PHRASES = (
    "Still accurate",
    "Still correct",
    "saves today's date",
    "keep matching",
    "Matching does not stop",
    "confirm your collection",
)


class _CaptureBot:
    """A bot stub that records the components a status DM sends."""

    def __init__(self):
        self.components = None
        self.rest = SimpleNamespace(
            create_dm_channel=self._dm_channel,
            create_message=self._create_message,
        )

    async def _dm_channel(self, _discord_id):
        return SimpleNamespace(id=99)

    async def _create_message(self, channel=None, components=None, flags=None):
        self.components = components
        return SimpleNamespace(id=1)


def test_fwa_callout_is_one_compact_red_text():
    """The FWA warning is a red bar, one Text, two short lines - nothing else."""
    callout = cards_command._fwa_warning()
    payload = _built(callout)
    assert payload["accent_color"] == int(cards_command.RED_ACCENT)
    children = payload["components"]
    assert len(children) == 1, "the compact callout holds exactly one Text"
    assert children[0]["type"] == int(hikari.ComponentType.TEXT_DISPLAY)
    lines = str(children[0]["content"]).splitlines()
    assert lines == [
        "⚠️ **FWA — Wait for war**",
        "Do not trade until war starts.",
    ]


def test_accepted_trade_dm_is_one_container_plus_compact_fwa():
    """FWA rides as the compact callout; nothing else adds a container."""
    view = cards_command._accepted_trade_dm(_trade(), fwa_relevant=True)
    assert len(view) == 2, "main container + compact FWA callout only"
    fwa_payload = _built(view[1])
    assert fwa_payload["accent_color"] == int(cards_command.RED_ACCENT)
    assert len(fwa_payload["components"]) == 1

    text = _text(view)
    for label in (
        "**You give:**", "**You receive:**",
        "**Your account:**", "**Trading with:**", "**Next:**",
    ):
        assert label in text, f"label grammar lost {label}"
    assert "I sent my card" in text
    assert "reserved until you confirm" in text

    same_clan = cards_command._accepted_trade_dm(
        _trade(status="ready", holder_clan_tag="#HOME",
               holder_clan_name="Home Clan"),
        fwa_relevant=False,
    )
    assert len(same_clan) == 1, "no callout, no extra container"
    assert "moves clans" not in _text(same_clan)


def test_noahs_ark_is_a_quiet_line_not_a_container():
    """Optional help is subtext inside the main container, never a blue card."""
    view = cards_command._accepted_trade_dm(_trade(), fwa_relevant=False)
    assert len(view) == 1
    text = _text(view)
    assert "-# ℹ️ Need a place to trade?" in text
    assert f"[**Open Noahs Ark**]({cards_command.NOAHS_ARK_LINK})" in text
    assert cards_command.NOAHS_ARK_TAG in text
    for container in view:
        assert _built(container).get("accent_color") != int(BLUE_ACCENT), (
            "Noahs Ark must not become a blue container again"
        )

    # Same clan needs no meeting place; an Ark-side trade offers none either.
    assert "Noahs Ark" not in _text(cards_command._accepted_trade_dm(
        _trade(status="ready"), fwa_relevant=False
    ))
    assert "Noahs Ark" not in _text(cards_command._accepted_trade_dm(
        _trade(holder_clan_tag=cards_command.NOAHS_ARK_TAG),
        fwa_relevant=False,
    ))


def test_holder_accept_feedback_shares_grammar_and_callout():
    view = cards_command._holder_accept_feedback(
        _trade(status="ready"),
        taken_card_id="electro_titan",
        status="ready",
        dm_sent=True,
        fwa_relevant=True,
        tag="#HOLD",
    )
    assert len(view) == 2, "feedback panel + compact FWA callout"
    assert _built(view[1])["accent_color"] == int(cards_command.RED_ACCENT)
    text = _text(view)
    for label in ("**You give:**", "**You receive:**", "**Trading with:**",
                  "**Next:**"):
        assert label in text
    assert "My trades" in text and "I sent my card" in text
    assert "I told them by DM." in text
    assert "Your account" not in text, (
        "the holder acted from this panel; their account needs no line"
    )


def test_status_dm_is_slim_and_names_only_the_reader():
    trade = _trade()
    line = cards_command._reader_account_line(trade, 111)
    assert line == "-# Account: Requester · `#REQ`"
    assert cards_command._reader_account_line(trade, 222).endswith("`#HOLD`")
    assert cards_command._reader_account_line(trade, 999) == ""

    bot = _CaptureBot()
    sent = asyncio.run(cards_command._notify_trade_status(
        bot, trade, recipient_id=111,
        title="Card proposal expired",
        detail="Nobody answered within 12 hours, so it closed. Nothing changed.",
    ))
    assert sent is True
    view = bot.components
    assert len(view) == 1, "a status DM is one container"
    payload = _built(view[0])
    assert "accent_color" not in payload or payload["accent_color"] is None, (
        "a terminal notice carries no accent"
    )
    text = _text(view)
    assert "Card proposal expired" in text
    assert "#REQ" in text and "#HOLD" not in text, (
        "only the reader's own account is named"
    )
    assert "Run /cards here or in the server" not in text
    assert all("type" not in n or n["type"] != int(
        hikari.ComponentType.SEPARATOR
    ) for n in _nodes(view)), "no separators inside a slim status DM"


def test_rendered_screens_expose_no_freshness_confirmation():
    """The obsolete concept is gone from every representative screen."""
    account = _account()
    stale = {
        "_id": "#ME",
        "cards": {"wizard": 3},
        "complete_categories": [category.id for category in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc) - timedelta(days=30),
    }
    screens = {
        "dashboard": cards_command._dashboard(
            account, stale, account_count=2
        ),
        "editor": cards_command._quantity_editor(account, stale, "elixir"),
        "trades": cards_command._trades_view(account, []),
        "paused": cards_command._trading_paused_view(account),
        "scan_review": cards_command._scan_review(
            account,
            cards_preview._preview_inventory(),
            "draft",
            cards_preview._preview_partial_draft(),
        ),
    }
    for name, view in screens.items():
        text = _text(view)
        for phrase in FRESHNESS_PHRASES:
            assert phrase not in text, f"{name} still says {phrase!r}"
        assert not any(
            i.startswith("cards_confirm:") for i in _custom_ids(view)
        ), f"{name} still renders the removed freshness button"


def test_no_cards_screen_mounts_the_decorative_footer():
    account = _account()
    inventory = cards_preview._preview_inventory()
    views = [
        cards_command._dashboard(account, inventory, account_count=1),
        cards_command._quantity_editor(account, inventory, "elixir"),
        cards_command._trades_view(account, []),
        cards_command._scan_upload_prompt(
            account, "s", usable_until=None
        ),
        cards_command._trade_proposal_dm(_trade(), controls=True),
        cards_command._accepted_trade_dm(_trade()),
        cards_command._checkin_dm("#ME", "Member"),
        cards_command._gem_ask_dm(_gem_ask(), preview=True),
        cards_command._notice("Title", "Body"),
        cards_command._trade_feedback("Title", "Body", "#ME"),
    ]
    for view in views:
        for node in _nodes(view):
            for item in node.get("items") or ():
                media = item.get("media") if isinstance(item, dict) else None
                assert "Red_Footer" not in str(media), (
                    "the decorative footer image is retired from Cards"
                )


def _gem_ask():
    return {
        "_id": "gem:#ME:#HOLD:meteor_golem",
        "kind": "gem_ask",
        "status": "pending",
        "card_id": "meteor_golem",
        "gem_cost": 50,
        "asker_name": "Member",
        "holder_name": "Holder",
        "generation": 1,
    }


def test_scanner_failure_copy_accepts_one_row():
    """A one-row image is valid, so no failure line may demand two rows."""
    draft = {
        "capture_issues": [
            {"image": 1, "warnings": ["no_valid_six_column_rows"]},
            {"image": 2, "warnings": ["some_unknown_code"]},
        ],
    }
    lines = cards_command._scan_capture_issue_lines(draft)
    assert len(lines) == 2
    joined = "\n".join(lines)
    assert "a complete six-card row" in joined
    assert "two complete" not in joined
    assert "expected two rows" not in joined


def test_scan_review_partial_is_short_and_states_the_save():
    account = _account()
    view = cards_command._scan_review(
        account,
        cards_preview._preview_inventory(),
        "draft",
        cards_preview._preview_partial_draft(),
    )
    assert len(view) == 1, "the review is one container"
    text = _text(view)
    assert "**I read 12 of 60 cards.** Nothing is saved yet." in text
    assert "Still to check: 48 cards" in text
    assert "**Save confirmed cards** saves the 12 cards I read." in text
    assert "Then set the rest in **Update collection**." in text
    assert "Nothing was guessed." in text
    for gone in (
        "does not retain the image files",
        "It changes nothing else",
        "stops being ready to trade",
    ):
        assert gone not in text
    labels = _labels(view)
    for expected in ("Save confirmed cards", "Update collection", "Cancel"):
        assert expected in labels
    assert len(text.splitlines()) <= 14, "the partial review stays short"


def test_trades_view_empty_offers_find_trades():
    account = _account()
    empty = cards_command._trades_view(account, [])
    assert "No open trades for this account." in _text(empty)
    assert "Find trades" in _labels(empty)

    busy = cards_command._trades_view(account, [_trade(status="pending")])
    assert "Find trades" not in _labels(busy)


class _PreviewRest:
    def __init__(self):
        self.messages = []

    async def create_dm_channel(self, _user_id):
        return SimpleNamespace(id=777)

    async def create_message(self, channel=None, components=None, flags=None):
        self.messages.append(components)
        return SimpleNamespace(id=1)


class _PreviewClans:
    def find(self, _query, _projection=None):
        class Cursor:
            async def to_list(self, length=None):
                return []

        return Cursor()

    async def find_one(self, _query, _projection=None):
        return None


def test_the_full_preview_suite_renders_within_discord_limits():
    """Every preview scenario - old and new - stays inside Discord's budgets.

    This is the offline equivalent of running /cards-dm-preview with
    "Everything": every message the harness would send is built through the
    production builders and checked against the 40-component, 4000-character
    and 25-option ceilings.
    """
    rest = _PreviewRest()
    sent = asyncio.run(cards_preview._send_previews(
        "all",
        me=1,
        bot=SimpleNamespace(rest=rest),
        mongo=SimpleNamespace(clans=_PreviewClans()),
    ))

    assert all(ok for _name, ok in sent), [n for n, ok in sent if not ok]
    names = [name for name, _ok in sent]
    for expected in (
        "20a · Accept feedback, different clans",
        "21a · Collection dashboard",
        "22a · Find trades",
        "22d · My trades, empty",
        "23a · Upload prompt",
        "24b · Notice, search unavailable",
    ):
        assert expected in names, f"preview scenario missing: {expected}"

    assert len(rest.messages) >= 25
    for view in rest.messages:
        nodes = _nodes(view)
        assert len([n for n in nodes if "type" in n]) <= 40
        for node in nodes:
            if "content" in node:
                assert len(str(node["content"])) <= 4_000
            options = node.get("options")
            if options is not None:
                assert 1 <= len(options) <= 25
        text = _text(view)
        for phrase in FRESHNESS_PHRASES:
            assert phrase not in text
        for node in nodes:
            for item in node.get("items") or ():
                media = item.get("media") if isinstance(item, dict) else None
                assert "Red_Footer" not in str(media)


def test_proposal_dm_is_gold_and_leads_with_labels():
    view = cards_command._trade_proposal_dm(_trade(), controls=True)
    payload = _built(view[0])
    assert payload["accent_color"] == int(cards_command.GOLD_ACCENT), (
        "a proposal waits on the reader: gold, not green"
    )
    text = _text(view)
    assert "wants your" not in text, "the lead sentence is gone"
    assert "**You give:**" in text
    assert "Nothing is reserved until you accept." in text
