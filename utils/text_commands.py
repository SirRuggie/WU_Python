"""Shared, non-executable Discord text commands stored beside bot configuration."""
import re
import ipaddress
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlsplit
import hikari
from pymongo.write_concern import WriteConcern

GUILD_ID = 644963518025826315
PATTERN = re.compile(r'![a-z0-9][a-z0-9_-]{0,31}', re.ASCII)
log = logging.getLogger(__name__)
_recent = OrderedDict()


def collection(db):
    # Same configured database as bot_config; permanent collection, no TTL.
    return db.bot_config.database.get_collection('text_commands', write_concern=WriteConcern(w='majority', wtimeout=10000))


def command_name(value):
    if not isinstance(value, str) or not PATTERN.fullmatch(value.strip().lower()):
        raise ValueError('Use ! followed by 1–32 letters, numbers, hyphens or underscores.')
    return value.strip().lower()


FIELDS = ('command', 'enabled', 'text', 'title', 'description', 'image_url',
          'color', 'blocks', 'allow_pings', 'choose_recipient', 'recipient_ping',
          'delete_trigger', 'allowed_channel_ids', 'allowed_role_ids')


def legacy_blocks(row):
    blocks=[]
    if row.get('title'):blocks.append({'type':'text','text':'## '+row['title']})
    if row.get('description'):blocks.append({'type':'text','text':row['description']})
    if row.get('image_url'):blocks.append({'type':'image','url':row['image_url'],'description':'Reply image'})
    return blocks


def public_url(value, label, limit=1000):
    if not isinstance(value,str) or not value or len(value)>limit:
        raise ValueError(f'Enter a {label} link of at most {limit} characters.')
    try:
        url=urlsplit(value);host=url.hostname or ''
        if url.scheme!='https' or not host or url.username or url.password or '.' not in host or host.endswith(('.', '.local', '.localhost', '.internal')) or url.port not in (None,443):raise ValueError()
        try:ipaddress.ip_address(host)
        except ValueError:
            if host.replace('.','').isdigit():raise ValueError()
        else:raise ValueError()
    except ValueError:raise ValueError(f'Use a public HTTPS {label} link.') from None
    return value


def validate(values, *, nested=False):
    if not isinstance(values,dict) or set(values)-set(FIELDS):raise ValueError('Check the command fields.')
    result = {'command': command_name(values.get('command')),
              'enabled': values.get('enabled', True),
              'allow_pings': values.get('allow_pings', False),
              'choose_recipient': values.get('choose_recipient', False),
              'recipient_ping': values.get('recipient_ping', False),
              'delete_trigger': values.get('delete_trigger', True)}
    if any(type(result[key]) is not bool for key in
           ('enabled', 'allow_pings', 'choose_recipient', 'recipient_ping',
            'delete_trigger')):
        raise ValueError('Choose whether the command and pings are enabled.')
    for key in ('allowed_channel_ids', 'allowed_role_ids'):
        ids = values.get(key, [])
        if not isinstance(ids, list) or len(ids) > 100 or any(
            not isinstance(value, str) or not re.fullmatch(r'[0-9]{15,22}', value) for value in ids
        ):
            raise ValueError('Choose up to 100 channels or roles from this server.')
        result[key] = list(dict.fromkeys(ids))
    for key,limit in (('text',2000),('title',256),('description',4000),('image_url',1000)):
        value=values.get(key,'')
        if not isinstance(value,str) or len(value)>limit:raise ValueError(f'{key.replace("_"," ").title()} must be at most {limit} characters.')
        result[key]=value.strip()
    color=values.get('color','#e2b332')
    if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Choose a valid embed color.')
    result['color']=color
    blocks=values.get('blocks',legacy_blocks(result))
    if not isinstance(blocks,list) or len(blocks)>15:raise ValueError('Use up to 15 embed blocks.')
    cleaned=[];total=len(result['text']);count=2 if result['text'] else 1
    for block in blocks:
        if not isinstance(block,dict):raise ValueError('Choose a valid embed block.')
        name=block.get('name','')
        if not isinstance(name,str) or len(name)>80:raise ValueError('Keep block names within 80 characters.')
        block={key:value for key,value in block.items() if key!='name'}
        kind=block.get('type');count+=1
        if kind=='text':
            if set(block)-{'type','text'} or not isinstance(block.get('text'),str) or not block['text'].strip() or len(block['text'])>4000:raise ValueError('Each text block needs 1–4,000 characters.')
            cleaned.append({'type':kind,'text':block['text'].strip()});total+=len(block['text'])
        elif kind=='image':
            description=block.get('description','')
            if set(block)-{'type','url','description'} or not isinstance(description,str) or len(description)>1024:raise ValueError('Keep the image description within 1,024 characters.')
            cleaned.append({'type':kind,'url':public_url(block.get('url'),'image'),'description':description})
        elif kind=='container':
            if nested or set(block)-{'type','color','spoiler','blocks'} or type(block.get('spoiler',False)) is not bool:raise ValueError('Cards cannot contain other cards.')
            child=validate(dict(command=result['command'],color=block.get('color','#e2b332'),blocks=block.get('blocks')),nested=True)
            cleaned.append({'type':'container','color':child['color'],'spoiler':block.get('spoiler',False),'blocks':child['blocks']})
        elif kind=='file':
            if set(block)-{'type','file_id','filename','size','spoiler'} or not isinstance(block.get('file_id'),str) or not re.fullmatch(r'[a-f0-9]{64}',block['file_id']) or not isinstance(block.get('filename'),str) or not re.fullmatch(r'[A-Za-z0-9_. -]{1,100}',block['filename']) or type(block.get('size')) is not int or not 1<=block['size']<=8*1024*1024 or type(block.get('spoiler',False)) is not bool:raise ValueError('Upload a file up to 8 MB.')
            cleaned.append({'type':'file','file_id':block['file_id'],'filename':block['filename'],'size':block['size'],'spoiler':block.get('spoiler',False)})
        elif kind=='actions':
            buttons=block.get('buttons')
            if set(block)-{'type','buttons'} or not isinstance(buttons,list) or not 1<=len(buttons)<=5:raise ValueError('Use 1–5 action buttons per row.')
            buttons=[validate_action_item(button) for button in buttons]
            cleaned.append({'type':'actions','buttons':buttons})
        elif kind=='select':
            options=block.get('options');placeholder=block.get('placeholder','Choose an option')
            if set(block)-{'type','options','placeholder'} or not isinstance(placeholder,str) or len(placeholder)>150 or not isinstance(options,list) or not 1<=len(options)<=25:raise ValueError('A dropdown needs 1–25 options and a short placeholder.')
            options=[validate_action_item(option) for option in options]
            if len({o['label'] for o in options})!=len(options):raise ValueError('Give each dropdown option a different label.')
            cleaned.append({'type':'select','placeholder':placeholder,'options':options})
        elif kind=='gallery':
            items=block.get('items')
            if set(block)-{'type','items'} or not isinstance(items,list) or not 1<=len(items)<=10:raise ValueError('A gallery needs 1–10 images or videos.')
            media=[]
            for item in items:
                if not isinstance(item,dict) or set(item)-{'url','description','spoiler'} or not isinstance(item.get('description',''),str) or len(item.get('description',''))>1024 or type(item.get('spoiler',False)) is not bool:raise ValueError('Check the gallery description and spoiler setting.')
                media.append({'url':public_url(item.get('url'),'media'),'description':item.get('description',''),'spoiler':item.get('spoiler',False)})
            cleaned.append({'type':kind,'items':media})
        elif kind=='section':
            texts=block.get('texts');accessory=block.get('accessory')
            if set(block)-{'type','texts','accessory'} or not isinstance(texts,list) or not 1<=len(texts)<=3 or any(not isinstance(t,str) or not t.strip() or len(t)>4000 for t in texts):raise ValueError('A section needs 1–3 text fields.')
            if not isinstance(accessory,dict):raise ValueError('Add a section thumbnail or link button.')
            if accessory.get('type')=='thumbnail':
                if set(accessory)-{'type','url','description','spoiler'} or not isinstance(accessory.get('description',''),str) or len(accessory.get('description',''))>1024 or type(accessory.get('spoiler',False)) is not bool:raise ValueError('Check the thumbnail settings.')
                side={'type':'thumbnail','url':public_url(accessory.get('url'),'thumbnail'),'description':accessory.get('description',''),'spoiler':accessory.get('spoiler',False)}
            elif accessory.get('type')=='button':
                if set(accessory)-{'type','url','label'} or not isinstance(accessory.get('label'),str) or not 1<=len(accessory['label'].strip())<=80:raise ValueError('The section button needs a label.')
                side={'type':'button','url':public_url(accessory.get('url'),'button',512),'label':accessory['label'].strip()}
            else:raise ValueError('Choose a thumbnail or link button.')
            total+=sum(len(t) for t in texts);count+=len(texts)+1
            cleaned.append({'type':kind,'texts':[t.strip() for t in texts],'accessory':side})
        elif kind=='separator':
            if set(block)-{'type','divider','spacing'} or type(block.get('divider',True)) is not bool or type(block.get('spacing',1)) is not int or block.get('spacing',1) not in (1,2):raise ValueError('Choose a valid separator.')
            cleaned.append({'type':kind,'divider':block.get('divider',True),'spacing':block.get('spacing',1)})
        elif kind=='buttons':
            buttons=block.get('buttons')
            if set(block)-{'type','buttons'} or not isinstance(buttons,list) or not 1<=len(buttons)<=5:raise ValueError('Each button row needs 1–5 links.')
            links=[]
            for button in buttons:
                if not isinstance(button,dict) or set(button)-{'label','url'} or not isinstance(button.get('label'),str) or not 1<=len(button['label'].strip())<=80:raise ValueError('Each link button needs a label of 1–80 characters.')
                links.append({'label':button['label'].strip(),'url':public_url(button.get('url'),'button',512)})
            count+=len(links);cleaned.append({'type':kind,'buttons':links})
        else:raise ValueError('Choose text, image, separator, or link buttons.')
        if name.strip():cleaned[-1]['name']=name.strip()
    total=len(result['text'])+sum(text_length(b) for b in cleaned)
    if total+(26 if result['choose_recipient'] else 0)>4000:raise ValueError('Keep all message text together within 4,000 characters.')
    count=component_count(cleaned)+bool(result['text'])
    files=[b for _,b in walk_blocks(cleaned) if b['type']=='file']
    if len(files)>10 or sum(b['size'] for b in files)>8*1024*1024:raise ValueError('Use at most 10 files, totaling 8 MB per message.')
    if count+(2 if result['choose_recipient'] else 0)>40:raise ValueError('This message has too many components. Remove a button row or block.')
    if not result['text'] and not any(b['type']!='separator' for b in cleaned):raise ValueError('Add message text or embed content.')
    result['blocks']=cleaned
    # Blocks are the canonical V2 layout. Legacy fields remain for old history records.
    result.update(title='',description='',image_url='')
    return result


def validate_action_item(item):
    if not isinstance(item,dict) or set(item)-{'label','style','action'} or not isinstance(item.get('label'),str) or not 1<=len(item['label'].strip())<=80 or type(item.get('style',1)) is not int or item.get('style',1) not in (1,2,3,4):raise ValueError('Each action needs a label and button color.')
    action=item.get('action')
    if not isinstance(action,dict):raise ValueError('Choose what the action does.')
    kind=action.get('kind')
    if kind=='reply' and set(action)=={'kind','command'}:action={'kind':kind,'command':command_name(action['command'])}
    elif kind in ('add_role','remove_role') and set(action)=={'kind','role_id'} and isinstance(action['role_id'],str) and re.fullmatch(r'[0-9]{15,22}',action['role_id']):action=dict(action)
    else:raise ValueError('Choose a saved reply or a role action.')
    return {'label':item['label'].strip(),'style':item.get('style',1),'action':action}


def walk_blocks(blocks,prefix=''):
    for index,block in enumerate(blocks):
        path=prefix+str(index)
        yield path,block
        if block['type']=='container':yield from walk_blocks(block['blocks'],path+'.')


def text_length(block):
    if block['type']=='container':return sum(text_length(b) for b in block['blocks'])
    if block['type']=='text':return len(block['text'])
    if block['type']=='section':return sum(map(len,block['texts']))
    return 0


def component_count(blocks):
    # Loose blocks share a default card; explicit cards are separate root components.
    count=0;loose=False
    for b in blocks:
        if b['type']=='container':count+=component_count(b['blocks']);loose=False
        else:
            if not loose:count+=1;loose=True
            count+=1
            if b['type'] in ('buttons','actions'):count+=len(b['buttons'])
            elif b['type']=='select':count+=1
            elif b['type']=='section':count+=len(b['texts'])+1
    return count


def fingerprint(row):
    import hashlib,json
    # Trigger cleanup is not part of the sent reply or its interactive actions.
    fields = {key:row.get(key) for key in FIELDS
              if key not in ('choose_recipient','recipient_ping','delete_trigger','allowed_channel_ids','allowed_role_ids')}
    if row.get('choose_recipient'):fields.update(choose_recipient=True,recipient_ping=True)
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()[:16]


def payload(row, file_data=None, *, recipient=None):
    from hikari.impl import ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text, MediaGalleryComponentBuilder as Gallery, MediaGalleryItemBuilder as Image, SeparatorComponentBuilder as Separator, MessageActionRowBuilder as Row, SectionComponentBuilder as Section, ThumbnailComponentBuilder as Thumbnail, FileComponentBuilder as File
    attachments=[]
    def custom(path):return 'ct:'+row['command']+':'+fingerprint(row)+':'+path
    def render(block,path):
        kind=block['type']
        if kind=='text':return Text(content=block['text'])
        if kind=='image':return Gallery(items=[Image(media=block['url'],description=block.get('description') or hikari.UNDEFINED)])
        if kind=='gallery':return Gallery(items=[Image(media=item['url'],description=item.get('description') or hikari.UNDEFINED,spoiler=item.get('spoiler',False)) for item in block['items']])
        if kind=='section':
            side=block['accessory']
            accessory=Thumbnail(media=side['url'],description=side.get('description') or hikari.UNDEFINED,spoiler=side.get('spoiler',False)) if side['type']=='thumbnail' else Row().add_link_button(side['url'],label=side['label']).components[0]
            return Section(components=[Text(content=text) for text in block['texts']],accessory=accessory)
        if kind=='separator':return Separator(divider=block['divider'],spacing=hikari.SpacingType(block['spacing']))
        if kind=='file':
            filename=path.replace('.','-')+'-'+block['filename']
            if file_data is not None:attachments.append(hikari.Bytes(file_data[block['file_id']],filename))
            return File(file='attachment://'+filename,spoiler=block.get('spoiler',False))
        if kind=='select':
            menu=Row().add_text_menu(custom(path),placeholder=block['placeholder'] or 'Choose an option',min_values=1,max_values=1)
            for index,option in enumerate(block['options']):menu.add_option(option['label'],str(index))
            return menu.parent
        buttons=Row()
        for index,button in enumerate(block['buttons']):
            if kind=='buttons':buttons.add_link_button(button['url'],label=button['label'])
            else:buttons.add_interactive_button(button['style'],custom(path+'.'+str(index)),label=button['label'])
        return buttons
    components=[];children=[]
    if recipient:
        kind, target = recipient
        recipient_text = Text(content=f'<@&{target}>' if kind=='role' else f'<@{target}>')
    if row.get('text'):components.append(Text(content=row['text']))
    def flush():
        if children:components.append(Container(accent_color=int(row['color'][1:],16),components=list(children)));children.clear()
    for index,block in enumerate(row.get('blocks',legacy_blocks(row))):
        if block['type']=='container':
            flush();components.append(Container(accent_color=int(block['color'][1:],16),spoiler=block.get('spoiler',False),components=[render(child,str(index)+'.'+str(j)) for j,child in enumerate(block['blocks'])]))
        else:children.append(render(block,str(index)))
    flush()
    if recipient:
        for index, component in enumerate(components):
            if isinstance(component, Container):
                components[index] = Container(accent_color=component.accent_color, spoiler=component.is_spoiler, components=[recipient_text, *component.components])
                break
        else:
            components.insert(0, recipient_text)
    pings=row.get('allow_pings',False)
    result={'components':components,'flags':hikari.MessageFlag.IS_COMPONENTS_V2,'mentions_everyone':pings,'user_mentions':pings,'role_mentions':pings}
    if recipient:
        ping=True
        # Saved mentions and the per-use recipient are independent settings.
        import json
        saved_text = json.dumps(row, ensure_ascii=False)
        users = {int(value) for value in re.findall(r'<@!?(\d+)>', saved_text)} if pings else set()
        roles = {int(value) for value in re.findall(r'<@&(\d+)>', saved_text)} if pings else set()
        if ping:
            (users if kind == 'user' else roles).add(int(target))
        result.update(mentions_everyone=pings,user_mentions=sorted(users) or False,role_mentions=sorted(roles) or False)
    if attachments:result['attachments']=attachments
    return result


async def record_delete_outcome(db, row, *, channel_id, error=None):
    """Best-effort runtime status, scoped to the delivered command revision.

    This metadata update never changes the editable revision or reply outcome.
    """
    selector = {'_id': f'{GUILD_ID}:{row["command"]}'}
    selector['revision'] = row['revision'] if 'revision' in row else {'$exists': False}
    if error is None:
        selector['last_delete_error'] = {'$exists': True}
        update = {'$unset': {'last_delete_error': ''}}
    else:
        reason = ('Missing Manage Messages permission' if isinstance(error, hikari.ForbiddenError)
                  else 'Delete failed (' + type(error).__name__[:48] + ')')
        update = {'$set': {'last_delete_error': {
            'at': datetime.now(timezone.utc).isoformat(),
            'channel_id': str(int(channel_id)), 'reason': reason[:96],
        }}}
    try:
        await collection(db).update_one(selector, update)
    except Exception:
        # The reply was delivered. A status write must not cause a resend.
        log.warning('Could not record trigger deletion outcome', exc_info=True)


def safe_outcome_reason(error):
    if isinstance(error, hikari.ForbiddenError):
        return 'Discord denied the reply. Check bot permissions.'
    if isinstance(error, hikari.NotFoundError):
        return 'The channel or linked item was not found.'
    if isinstance(error, (TimeoutError, hikari.InternalServerError)):
        return 'Delivery was not confirmed. Check Discord before trying again.'
    if isinstance(error, ValueError) and str(error) in (
        'An attachment is missing or changed. Upload it again.',
        'An attachment is unreadable. Upload it again.',
    ):
        return str(error)
    return 'The reply could not be delivered. Check its content and bot permissions.'


async def record_use(db, row, channel_id, error=None):
    at = datetime.now(timezone.utc).isoformat()
    selector = {'_id': f'{GUILD_ID}:{row["command"]}',
                'revision': row['revision'] if 'revision' in row else {'$exists': False}}
    outcome = {'status': 'error' if error else 'ok', 'at': at,
               'channel_id': str(channel_id), 'reason': safe_outcome_reason(error) if error else ''}
    try:
        await collection(db).update_one(selector, {
            '$inc': {'use_count': 1},
            '$set': {'last_used_at': at, 'last_outcome': outcome},
        })
    except Exception:
        log.warning('Could not record command usage outcome', exc_info=True)


async def within_scope(row, event, bot):
    channels = row['allowed_channel_ids']
    if channels and str(event.channel_id) not in channels:
        return False
    roles = row['allowed_role_ids']
    if not roles:
        return True
    member = getattr(event.message, 'member', None)
    if member is None:
        member = await bot.rest.fetch_member(GUILD_ID, event.message.author.id)
    return bool(set(roles) & {str(role) for role in member.role_ids})


async def handle(event, db, bot):
    message = event.message
    if int(event.guild_id) != GUILD_ID or message.author.is_bot or getattr(message, 'webhook_id', None):
        return False
    try:
        parts = (message.content or '').strip().split()
        name = command_name(parts[0] if parts else '')
        mention = re.fullmatch(r'<@([!&]?)([0-9]{1,22})>', parts[1]) if len(parts) == 2 else None
        if len(parts) > 1 and mention is None:
            return False
    except ValueError:
        return False
    row = None
    attempted = False
    try:
        row = await collection(db).find_one({'_id': f'{GUILD_ID}:{name}', 'enabled': True})
        if not row:
            return False
        # Validate persisted input and check scope before replying or deleting.
        clean = validate({key: row[key] for key in FIELDS if key in row})
        if not await within_scope(clean, event, bot):
            return False
        # Only enabled, existing commands consume a cooldown.
        import time
        now = time.monotonic()
        key = (int(event.channel_id), name)
        if now - _recent.get(key, -100) < 5:
            return True
        _recent[key] = now
        _recent.move_to_end(key)
        while len(_recent) > 5000:
            _recent.popitem(last=False)
        recipient = None
        if clean.get('choose_recipient'):
            async def explain(text):
                await bot.rest.create_message(event.channel_id, content=text, mentions_everyone=False, user_mentions=False, role_mentions=False)
            if mention is None:
                await explain(f'Use {name} @person or {name} @role.')
                return True
            kind, target = ('role' if mention[1] == '&' else 'user'), int(mention[2])
            if kind == 'role':
                roles = await bot.rest.fetch_roles(GUILD_ID)
                role = next((role for role in roles if int(role.id) == target), None)
                if role is None or target == GUILD_ID:
                    await explain('Choose a server role other than @everyone.')
                    return True
                if not role.is_mentionable:
                    member = await bot.rest.fetch_member(GUILD_ID, message.author.id)
                    permissions = hikari.Permissions.NONE
                    for own_role in roles:
                        if int(own_role.id) == GUILD_ID or own_role.id in member.role_ids:
                            permissions |= own_role.permissions
                    if not permissions & (hikari.Permissions.MENTION_ROLES | hikari.Permissions.ADMINISTRATOR):
                        guild = await bot.rest.fetch_guild(GUILD_ID)
                        if int(guild.owner_id) != int(message.author.id):
                            await explain('You cannot ping that role. Choose a mentionable role.')
                            return True
            else:
                try:
                    await bot.rest.fetch_member(GUILD_ID, target)
                except hikari.NotFoundError:
                    await explain('Choose a current server member.')
                    return True
            recipient = (kind, target)
        elif mention is not None:
            return False
        from utils.text_command_files import load_files
        attempted = True
        await bot.rest.create_message(event.channel_id, **payload(clean,await load_files(db,clean),recipient=recipient))
        await record_use(db, row, event.channel_id)
        if clean['delete_trigger']:
            try:
                await bot.rest.delete_message(event.channel_id, message.id)
            except hikari.NotFoundError:
                await record_delete_outcome(db, row, channel_id=event.channel_id)
            except Exception as error:
                # Delivery succeeded. Never resend or lose the reply over cleanup.
                log.warning('Trigger reply sent but original message could not be deleted; check Manage Messages permission', exc_info=True)
                await record_delete_outcome(db, row, channel_id=event.channel_id,
                                            error=error)
            else:
                await record_delete_outcome(db, row, channel_id=event.channel_id)
        return True
    except Exception as error:
        if row is not None and attempted:
            await record_use(db, row, event.channel_id, error)
        log.exception('Text command could not be delivered: %s', name)
        return True
