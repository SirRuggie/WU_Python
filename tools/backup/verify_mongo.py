"""Restore a dump only into a fresh, authenticated loopback MongoDB server."""
import gzip
import hashlib
import json
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import time
from urllib.parse import quote

from bson import json_util
from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument
from pymongo import MongoClient


def verify_dump(dump: Path, scratch: Path, tools: Path, run):
    scratch.mkdir(mode=0o700)
    data = scratch / 'data'
    data.mkdir(mode=0o700)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config = scratch / 'restore.yml'
    local = bootstrap = None
    with (scratch / 'mongod.log').open('w') as log:
        proc = subprocess.Popen([str(tools / 'mongod'), '--dbpath', str(data), '--bind_ip', '127.0.0.1',
            '--port', str(port), '--auth', '--nounixsocket', '--setParameter', 'ttlMonitorEnabled=false',
            '--wiredTigerCacheSizeGB', '0.25'], stdout=log, stderr=log)
        try:
            uri = f'mongodb://127.0.0.1:{port}/?directConnection=true'
            bootstrap = MongoClient(uri, serverSelectionTimeoutMS=500, connectTimeoutMS=500)
            for _ in range(60):
                if proc.poll() is not None:
                    raise RuntimeError('Isolated MongoDB restore server failed to start')
                try:
                    bootstrap.admin.command('ping')
                    break
                except Exception:
                    time.sleep(0.25)
            else:
                raise RuntimeError('Isolated MongoDB restore server startup timed out')
            password = secrets.token_urlsafe(32)
            bootstrap.admin.command('createUser', 'recovery', pwd=password, roles=[{'role': 'root', 'db': 'admin'}])
            local = MongoClient(uri, username='recovery', password=password, authSource='admin', serverSelectionTimeoutMS=5000)
            config.write_text(json.dumps({'uri': f'mongodb://recovery:{quote(password, safe="")}@127.0.0.1:{port}/?authSource=admin&directConnection=true'}))
            run([tools / 'mongorestore', '--config', config, '--gzip', '--stopOnError', dump])
            collections = documents = 0
            for folder in sorted(dump.iterdir()):
                if not folder.is_dir():
                    continue
                names = {p.name[:-8] for p in folder.glob('*.bson.gz')}
                db = local[folder.name]
                if set(db.list_collection_names()) != names:
                    raise RuntimeError('Restored Mongo collection list mismatch')
                for name in names:
                    expected = []
                    with gzip.open(folder / (name + '.bson.gz'), 'rb') as stream:
                        while header := stream.read(4):
                            if len(header) != 4:
                                raise RuntimeError('Truncated BSON header')
                            length = struct.unpack('<i', header)[0]
                            if not 5 <= length <= 16 * 1024 * 1024:
                                raise RuntimeError('Invalid BSON length')
                            raw = header + stream.read(length - 4)
                            if len(raw) != length:
                                raise RuntimeError('Truncated BSON document')
                            expected.append(hashlib.sha256(raw).hexdigest())
                    col = db.get_collection(name, codec_options=CodecOptions(document_class=RawBSONDocument))
                    actual = [hashlib.sha256(doc.raw).hexdigest() for doc in col.find({})]
                    if sorted(actual) != sorted(expected):
                        raise RuntimeError('Restored BSON content mismatch')
                    with gzip.open(folder / (name + '.metadata.json.gz'), 'rt') as stream:
                        metadata = json_util.loads(stream.read())
                    def clean(items):
                        return sorted([{k: v for k, v in item.items() if k not in ('ns', 'background')} for item in items], key=lambda i: i['name'])
                    if clean(metadata['indexes']) != clean(db[name].list_indexes()):
                        raise RuntimeError('Restored Mongo index mismatch')
                    if metadata.get('options', {}) != next(db.list_collections(filter={'name': name}))['options']:
                        raise RuntimeError('Restored Mongo collection options mismatch')
                    collections += 1
                    documents += len(actual)
            return {'collections': collections, 'documents': documents}
        finally:
            config.unlink(missing_ok=True)
            if local is not None:
                local.close()
            if bootstrap is not None:
                bootstrap.close()
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
