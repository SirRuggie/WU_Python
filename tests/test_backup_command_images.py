import importlib.util,io,json
from types import SimpleNamespace as NS
import pytest
spec=importlib.util.spec_from_file_location('backup_images','tools/backup/command_images.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_capture_cached_and_restored(tmp_path):
    key='content/command-triggers/1/image.png';calls=[]
    def get(**kwargs):calls.append(kwargs);return {'Body':io.BytesIO(b'image')}
    client=NS(get_paginator=lambda _:NS(paginate=lambda **kw:[{'Contents':[{'Key':key,'ETag':'v1','Size':5}]}]),get_object=get)
    assert module.capture(tmp_path,tmp_path,client,'bucket')==1
    assert module.capture(tmp_path,tmp_path,client,'bucket')==1
    assert len(calls)==1 and calls[0]['IfMatch']=='v1'
    assert module.verify(tmp_path)==1
    manifest=json.loads((tmp_path/'command-images/manifest.json').read_text())
    (tmp_path/'command-images'/manifest[key]['file']).write_bytes(b'other')
    with pytest.raises(RuntimeError,match='checksum'):module.verify(tmp_path)

def test_old_snapshot_and_oversized(tmp_path):
    assert module.verify(tmp_path)==0
    client=NS(get_paginator=lambda _:NS(paginate=lambda **kw:[{'Contents':[{'Key':'large','ETag':'v1','Size':11*1024*1024}]}]))
    with pytest.raises(RuntimeError,match='size limit'):module.capture(tmp_path,tmp_path,client,'bucket')

def test_all_editable_artwork_prefixes_are_protected(tmp_path):
    prefixes=[]
    def pages(**kwargs):
        prefix=kwargs['Prefix'];prefixes.append(prefix)
        return [{'Contents':[{'Key':prefix+'image.png','ETag':'v1','Size':5}]}]
    client=NS(get_paginator=lambda _:NS(paginate=pages),get_object=lambda **kw:{'Body':io.BytesIO(b'image')})
    assert module.capture(tmp_path,tmp_path,client,'bucket')==4
    assert set(prefixes)=={'content/command-triggers/','clans/','fwa/bases/','content/recruit/'}
    manifest=json.loads((tmp_path/'command-images/manifest.json').read_text())
    assert set(manifest)=={prefix+'image.png' for prefix in prefixes}
    assert module.verify(tmp_path)==4


def test_folder_markers_skipped_but_empty_images_rejected(tmp_path):
    item={'Key':'clans/','ETag':'empty','Size':0}
    client=NS(get_paginator=lambda _:NS(paginate=lambda **kw:[{'Contents':[item]}]))
    assert module.capture(tmp_path,tmp_path,client,'bucket')==0
    item['Key']='clans/empty.png'
    with pytest.raises(RuntimeError,match='size limit'):module.capture(tmp_path,tmp_path,client,'bucket')


def test_client_config_uses_five_total_standard_attempts(tmp_path, monkeypatch):
    import boto3
    options = []
    client = NS(get_paginator=lambda _: NS(paginate=lambda **kw: []))
    monkeypatch.setattr(boto3, 'client', lambda *args, **kw: options.append(kw) or client)
    monkeypatch.setattr(module, 'dotenv_values', lambda _: {
        'R2_BUCKET': 'fixture', 'R2_ACCOUNT_ID': 'fixture',
        'R2_ACCESS_KEY_ID': 'fixture', 'R2_SECRET_ACCESS_KEY': 'fixture',
    })
    assert module.capture(tmp_path, tmp_path) == 0
    config = options[0]['config']
    assert config.retries == {'mode': 'standard', 'total_max_attempts': 5}
    assert config.connect_timeout == 5
    assert config.read_timeout == 30


def test_mid_capture_failure_keeps_updated_manifest_consistent(tmp_path):
    from botocore.exceptions import ClientError
    items = [{'Key': 'clans/first.png', 'ETag': 'v1', 'Size': 3},
             {'Key': 'clans/second.png', 'ETag': 'v1', 'Size': 3}]
    calls = []
    def get(**kwargs):
        calls.append(kwargs['Key'])
        if len(calls) == 2:
            raise ClientError({'Error': {'Code': 'InternalError'}}, 'GetObject')
        return {'Body': io.BytesIO(b'new')}
    client = NS(get_paginator=lambda _: NS(paginate=lambda **kw: [{'Contents': items}]), get_object=get)
    with pytest.raises(ClientError):
        module.capture(tmp_path, tmp_path, client, 'fixture')
    saved = json.loads((tmp_path / 'command-images/manifest.json').read_text())
    assert set(saved) == {'clans/first.png'}
    assert module.verify(tmp_path) == 1


def test_manifest_write_failure_keeps_primary_capture_error(tmp_path, monkeypatch):
    from botocore.exceptions import ClientError
    error = ClientError({'Error': {'Code': 'InternalError'}}, 'ListObjectsV2')
    def pages(**kwargs):
        raise error
    client = NS(get_paginator=lambda _: NS(paginate=pages))
    from pathlib import Path
    def write(self, *args, **kwargs):
        raise OSError('fixture disk full')
    monkeypatch.setattr(Path, 'write_text', write)
    with pytest.raises(ClientError) as raised:
        module.capture(tmp_path, tmp_path, client, 'fixture')
    assert raised.value is error
    assert isinstance(raised.value.__cause__, OSError)
