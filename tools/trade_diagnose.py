"""Print everything the card system knows about one player tag. Read-only.

Written for the first live "where did my card go" report: a member's editor
showed a card as "in a trade" while My trades showed nothing, and the chat
log could not say which of three histories had actually happened. This is
the difference between diagnosing from data and guessing from memory.

Run it on the host, with the venv interpreter, while the bot is up - it only
reads:

    /home/wubot/wu-bot/venv/bin/python tools/trade_diagnose.py '#8LR09CJP8'

It prints the inventory's counts and reservations for cards that carry one,
then every card_trades document touching the tag - trades either side, gem
asks, open requests, leases, proposal slots - newest first, with the fields
that decide an outcome. Nothing is redacted because everything here is the
family's own trading data; the connection string is never printed.
"""

import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient


def _tag(value: str) -> str:
    cleaned = value.strip().upper().replace("O", "0")
    if not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    return cleaned


def _show(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value


def _dump(title: str, document: dict, fields: tuple) -> None:
    print(f"\n--- {title} ---")
    for field in fields:
        if field in document:
            print(f"  {field}: {json.dumps(_show(document[field]), default=str)}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: trade_diagnose.py '#PLAYERTAG'")
        return 2
    tag = _tag(sys.argv[1])
    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    if not uri:
        print("MONGODB_URI is not set; run from the bot directory.")
        return 2
    database = MongoClient(uri).get_database("settings")

    inventory = database.card_inventories.find_one({"_id": tag})
    print(f"===== inventory {tag} =====")
    if not inventory:
        print("  (no inventory document)")
    else:
        for field in (
            "player_name", "discord_id", "guild_id", "clan_name",
            "complete_categories", "confirmed_at", "updated_at",
            "trading_paused", "inventory_revision",
        ):
            if field in inventory:
                print(f"  {field}: {json.dumps(_show(inventory[field]), default=str)}")
        reservations = inventory.get("card_trade_reservations") or {}
        print(f"  card_trade_reservations: {json.dumps(_show(reservations), default=str)}")
        cards = inventory.get("cards") or {}
        for card_id in sorted(set(reservations) | {"drop_ship"}):
            print(f"  count[{card_id}]: {cards.get(card_id)!r}")

    trade_fields = (
        "_id", "kind", "status", "created_at", "updated_at",
        "requester_tag", "requester_name", "requester_discord_id",
        "holder_tag", "holder_name", "holder_discord_id",
        "wanted_card_id", "given_card_id", "taken_card_id",
        "accept_deadline_at", "reservation_until", "expires_at",
        "requester_confirmed_at", "holder_confirmed_at",
        "confirm_deadline_at", "swap_leg_progress", "failure",
        "review_expires_at", "cleanup_pending", "channel_message_id",
        "declined_at", "cancelled_at", "expired_at", "claimed_at",
        "claim_until", "claimed_by_tag", "trade_id",
        "asker_tag", "card_id", "generation",
    )
    query = {"$or": [
        {"requester_tag": tag},
        {"holder_tag": tag},
        {"asker_tag": tag},
        {"claimed_by_tag": tag},
        {"_id": {"$regex": tag.replace("#", "\\#")}},
    ]}
    rows = sorted(
        database.card_trades.find(query),
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        reverse=True,
    )
    print(f"\n===== card_trades touching {tag}: {len(rows)} =====")
    for row in rows:
        _dump(
            f"{row.get('kind', '?')} · {row.get('status', '?')} · {row.get('_id')}",
            row,
            trade_fields,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
