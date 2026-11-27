"""Approved migration-only server role seeds; dry-run by default."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from utils import server_roles

SEED_ROLES = [{'label': 'Base Builder',
  'order': 0,
  'role_id': '747868210161778779',
  'short_line': 'Discuss, design and test CoC Base designs'},
 {'label': 'Bot Developer',
  'order': 1,
  'role_id': '728454164186660914',
  'short_line': 'Discuss Discord bot development.'},
 {'label': 'NASDAQ',
  'order': 2,
  'role_id': '767736693137997854',
  'short_line': 'Share and discuss different investment strategies.'},
 {'label': 'Graphic Designer',
  'order': 3,
  'role_id': '744293746962595971',
  'short_line': 'Share, post and discuss graphic design ideas.'},
 {'label': 'Lazy Clan Participant',
  'order': 4,
  'role_id': '772313841090297886',
  'short_line': 'Get this role to see the LazyCWL signups channel.'},
 {'label': 'VC Participant',
  'order': 5,
  'role_id': '1148955348598788166',
  'short_line': 'A ping for members who want to talk.'}]

async def seed(mongo, guild_id, *, safe_role_ids, apply=False):
    preview = await server_roles.seed(mongo, guild_id, SEED_ROLES, apply=False)
    if preview.get('conflicts'):
        if apply:
            raise server_roles.ServerRoleOverlap(preview['conflicts'])
        return preview
    if any(row['role_id'] not in safe_role_ids for row in SEED_ROLES):
        raise ValueError('A configured server role is no longer safe. No seed was written.')
    return await server_roles.seed(mongo, guild_id, SEED_ROLES, apply=True) if apply else preview


def main(argv=None):
    import argparse
    import asyncio
    import json
    import os
    from dotenv import load_dotenv
    from utils.mongo import MongoClient
    from tools.migrate_town_halls import safe_discord_roles
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guild-id', required=True, type=int)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    load_dotenv()
    async def run():
        mongo = MongoClient(os.environ['MONGODB_URI'], connect=False)
        try:
            return await seed(mongo, args.guild_id, safe_role_ids=await safe_discord_roles(mongo, args.guild_id), apply=args.apply)
        finally:
            await mongo.close()
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    return 1 if result.get("conflicts") else 0


if __name__ == '__main__':
    raise SystemExit(main())
