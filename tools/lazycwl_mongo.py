"""Read-only LazyCWL MongoDB audit; --apply-schema performs the additive migration.

Stop the bot before applying. Never prints connection strings or player data.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from utils.mongo import MongoClient
from utils.lazy_cwl_schema import apply_schema, audit_collection
from utils.lazy_cwl_store import ensure_indexes


async def run(apply: bool):
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    uri = os.environ.get('MONGODB_URI')
    if not uri:
        raise SystemExit('MONGODB_URI is not configured.')
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    try:
        collection = client.lazy_cwl_lists
        if apply:
            await ensure_indexes(client)
            result = await apply_schema(collection)
        else:
            result = await audit_collection(collection)
        print(json.dumps(result, sort_keys=True))
    finally:
        await client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply-schema', action='store_true', help='Backfill schema_version and install strict validation. Stop the bot first.')
    args = parser.parse_args()
    asyncio.run(run(args.apply_schema))
