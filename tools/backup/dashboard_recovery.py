"""Initialize once while stopped, or verify/export the latest Mongo state.

Never overwrites an existing Mongo head. Export refuses an existing destination.
Credentials are loaded from private environment files, never command arguments.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import dotenv_values
from utils.cwl_dashboard_state import MongoDashboardState, database_lock, decode
from utils.mongo_routes import load_routes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['initialize', 'verify', 'export'])
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    settings = {**dotenv_values(args.env_file), **os.environ}
    owner = MongoDashboardState.open(settings.get('MONGODB_URI', ''),
        routes=load_routes(json.loads(settings.get('MONGODB_ROUTES') or '{}')))
    try:
        if args.action == 'initialize':
            path = settings['CWL_WEB_DB_PATH']
            with database_lock(path):
                counts = owner.seed(path)
            print('Initialized Mongo recovery state:', counts)
        else:
            doc = owner.collection.find_one({'_id': owner.key})
            if not doc:
                raise RuntimeError('Mongo recovery state is missing')
            db = decode(doc)
            try:
                if args.action == 'export':
                    if not args.output:
                        raise ValueError('--output is required')
                    # O_EXCL: never overwrite a live or previously recovered DB.
                    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(fd)
                    with sqlite3.connect(args.output) as target:
                        db.backup(target)
                print('Verified Mongo revision', doc['revision'], 'saved at', doc['saved_at'])
                print('Recovered table counts:', doc['tables'])
            finally:
                db.close()
    finally:
        owner.close()


if __name__ == '__main__':
    main()
