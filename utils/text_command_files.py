"""Bounded, content-addressed command attachments in the backed-up settings database."""
import hashlib,re
from datetime import datetime,timezone
from pymongo.write_concern import WriteConcern
from utils.text_commands import GUILD_ID,walk_blocks
MAX_BYTES=8*1024*1024

def collection(db):
    return db.bot_config.database.get_collection('text_command_files',write_concern=WriteConcern(w='majority',wtimeout=10000))

def filename(value):
    value=re.sub(r'[^A-Za-z0-9_. -]','_',value.rsplit('/',1)[-1].rsplit('\\',1)[-1])[:100].strip(' .')
    return value or 'attachment.bin'

async def store_file(db,data,name,actor):
    if not data or len(data)>MAX_BYTES:raise ValueError('Choose a file between 1 byte and 8 MB.')
    name=filename(name);key=hashlib.sha256(name.encode()+b'\0'+data).hexdigest()
    await collection(db).update_one({'_id':key},{'$setOnInsert':{'guild_id':GUILD_ID,'filename':name,'size':len(data),'data':data,'created_by':str(actor),'created_at':datetime.now(timezone.utc)}},upsert=True)
    return dict(file_id=key,filename=name,size=len(data))

async def load_files(db,row,*,metadata_only=False):
    result={}
    for _,block in walk_blocks(row.get('blocks',[])):
        if block['type']!='file':continue
        doc=await collection(db).find_one({'_id':block['file_id'],'guild_id':GUILD_ID}, {'data':0} if metadata_only else None)
        if not doc or doc.get('filename')!=block['filename'] or doc.get('size')!=block['size']:raise ValueError('An attachment is missing or changed. Upload it again.')
        if not metadata_only:
            data=doc.get('data',b'')
            if len(data)!=block['size'] or len(data)>MAX_BYTES:raise ValueError('An attachment is unreadable. Upload it again.')
            result[block['file_id']]=data
    return result
