#!/usr/bin/env python3
"""Read-only lookup of recruitment message delivery receipts. See --help."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def arguments():
    parser = argparse.ArgumentParser(
        description="Inspect settings.recruit_message_deliveries (read-only; never resends messages)."
    )
    parser.add_argument("--user-id", type=int, help="Recruit Discord ID")
    parser.add_argument("--channel-id", type=int, help="Ticket/channel Discord ID")
    parser.add_argument("--delivery-id", help="Full readable Mongo delivery ID")
    parser.add_argument(
        "--status", choices=["prepared", "sending", "retryable", "sent", "needs_review"]
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Newest records to display (1–100; default 20)",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    return args


async def main(args):
    from dotenv import load_dotenv
    from utils.mongo import MongoClient
    from utils.recruit_message_delivery import collection

    load_dotenv(ROOT / ".env")
    mongo = MongoClient(os.environ["MONGODB_URI"])
    try:
        query = {
            key: value
            for key, value in {
                "user_id": args.user_id,
                "channel_id": args.channel_id,
                "_id": args.delivery_id,
                "status": args.status,
            }.items()
            if value is not None
        }
        records = (
            await collection(mongo)
            .find(query)
            .sort("created_at", -1)
            .limit(args.limit)
            .to_list(length=args.limit)
        )
        fields = (
            "_id",
            "kind",
            "status",
            "user_id",
            "channel_id",
            "guild_id",
            "discord_nonce",
            "discord_message_id",
            "attempts",
            "created_at",
            "updated_at",
            "first_attempt_at",
            "last_attempt_at",
            "lease_until",
            "expires_at",
            "last_error",
            "recovered_from_history",
        )
        for row in records:
            view = {key: row[key] for key in fields if key in row}
            if row.get("guild_id") and row.get("discord_message_id"):
                view["message_url"] = (
                    f"https://discord.com/channels/{row['guild_id']}/{row['channel_id']}/{row['discord_message_id']}"
                )
            print(json.dumps(view, default=str, indent=2))
        print(f"{len(records)} delivery record(s). Read-only; no messages sent.")
    finally:
        await mongo.close()


if __name__ == "__main__":
    asyncio.run(main(arguments()))
