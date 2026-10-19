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
