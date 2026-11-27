"""Keep editable dashboard artwork bytes in the existing encrypted backup snapshots."""
import hashlib
import json
import os
from pathlib import Path

from dotenv import dotenv_values


PREFIXES = ('content/command-triggers/', 'clans/', 'fwa/bases/', 'content/recruit/')


def capture(root, stage, client=None, bucket=None):
    target = stage / 'command-images'
    target.mkdir(mode=0o700, exist_ok=True)
    manifest_path = target / 'manifest.json'
    saved = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    capture_error = None
    try:
        if client is None:
            import boto3
            from botocore.config import Config

            values = {**dotenv_values(root / '.env'), **dotenv_values(root / '.local/cwl-web.env')}
            bucket = values['R2_BUCKET']
            # https://botocore.amazonaws.com/v1/documentation/api/latest/reference/config.html#botocore.config.Config
            client = boto3.client(
                's3',
                endpoint_url=f"https://{values['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                aws_access_key_id=values['R2_ACCESS_KEY_ID'],
                aws_secret_access_key=values['R2_SECRET_ACCESS_KEY'],
                region_name='auto',
                config=Config(
                    connect_timeout=5,
                    read_timeout=30,
                    retries={'mode': 'standard', 'total_max_attempts': 5},
                ),
            )
        for prefix in PREFIXES:
            pages = client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix)
            for page in pages:
                for item in page.get('Contents', []):
                    # R2 folder markers contain no image data.
                    if item['Size'] == 0 and item['Key'].endswith('/'):
                        continue
                    key = item['Key']
                    filename = hashlib.sha256(key.encode()).hexdigest()
                    path = target / filename
                    previous = saved.get(key, {})
                    if (path.exists() and previous.get('etag') == item['ETag']
                            and hashlib.sha256(path.read_bytes()).hexdigest() == previous.get('sha256')):
                        continue
                    if not 0 < item['Size'] <= 10 * 1024 * 1024:
                        raise RuntimeError('Dashboard artwork exceeds backup size limit')
                    response = client.get_object(Bucket=bucket, Key=key, IfMatch=item['ETag'])
                    try:
                        data = response['Body'].read(10 * 1024 * 1024 + 1)
                    finally:
                        response['Body'].close()
                    if len(data) != item['Size']:
                        raise RuntimeError('Dashboard artwork changed during backup')
                    pending = path.with_suffix('.pending')
                    pending.write_bytes(data)
                    os.replace(pending, path)
                    saved[key] = {
                        'file': filename,
                        'etag': item['ETag'],
                        'sha256': hashlib.sha256(data).hexdigest(),
                        'size': len(data),
                    }
    except BaseException as error:
        capture_error = error
        raise
    finally:
        try:
            pending = manifest_path.with_suffix('.pending')
            pending.write_text(json.dumps(saved, indent=2))
            os.replace(pending, manifest_path)
        except Exception as manifest_error:
            if capture_error is None:
                raise
            # A provider error must not turn local manifest persistence failure into a skip.
            capture_error._artwork_manifest_write_failed = True
            # Preserve the original failure while retaining the persistence failure as its cause.
            raise capture_error from manifest_error
    verify(stage)
    return len(saved)


def verify(stage):
    target = stage / 'command-images'
    manifest = target / 'manifest.json'
    if not manifest.exists():
        return 0  # Older snapshots predate artwork capture.
    saved = json.loads(manifest.read_text())
    for item in saved.values():
        name = item['file']
        if len(name) != 64 or any(c not in '0123456789abcdef' for c in name):
            raise RuntimeError('Invalid artwork backup path')
        data = (target / name).read_bytes()
        if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise RuntimeError('Restored dashboard artwork checksum mismatch')
    return len(saved)
