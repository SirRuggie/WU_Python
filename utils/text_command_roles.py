"""Explicitly configured self-service roles, checked against the bot on every click."""
from datetime import datetime,timezone
from types import SimpleNamespace as NS
import hikari
from pymongo.write_concern import WriteConcern
from utils.text_commands import GUILD_ID
from utils.role_permissions import role_is_manageable

PRIVILEGED=(hikari.Permissions.ADMINISTRATOR|hikari.Permissions.MANAGE_GUILD|hikari.Permissions.MANAGE_ROLES|hikari.Permissions.MANAGE_CHANNELS|hikari.Permissions.MANAGE_WEBHOOKS|hikari.Permissions.BAN_MEMBERS|hikari.Permissions.KICK_MEMBERS|hikari.Permissions.MODERATE_MEMBERS|hikari.Permissions.MANAGE_MESSAGES|hikari.Permissions.MANAGE_THREADS|hikari.Permissions.MENTION_ROLES|hikari.Permissions.MANAGE_GUILD_EXPRESSIONS|hikari.Permissions.MANAGE_EVENTS|hikari.Permissions.MUTE_MEMBERS|hikari.Permissions.DEAFEN_MEMBERS|hikari.Permissions.MOVE_MEMBERS|hikari.Permissions.VIEW_AUDIT_LOG)

KNOWN_STAFF_ROLES={1003797104088592444,769130325460254740,993015846442127420}

async def protected_roles(db):
    cfg=await db.ticket_setup.find_one({'_id':'config'}) or {}
    blocked=set(KNOWN_STAFF_ROLES)
    for key,value in cfg.items():
        if 'role' in key and any(word in key for word in ('staff','recruiter','admin','moderator','support')):
            for item in (value if isinstance(value,list) else [value]):
                if str(item).isdigit():blocked.add(int(item))
    return blocked

def safe_role(role,blocked=KNOWN_STAFF_ROLES):
    return role is not None and not role.is_managed and int(role.id)!=GUILD_ID and int(role.id) not in blocked and not (role.permissions & PRIVILEGED)

async def perform(interaction,db,row,action):
    rest=interaction.app.rest
    roles={r.id:r for r in await rest.fetch_roles(GUILD_ID)}
    guild_data=await rest.fetch_guild(GUILD_ID)
    me=await rest.fetch_my_user();bot_member=await rest.fetch_member(GUILD_ID,me.id)
    author_id=int(row.get('updated_by',0))
    # A removed editor's old public controls must not keep granting access.
    await rest.fetch_member(GUILD_ID,author_id)
    grant=await db.bot_config.find_one({'_id':'dashboard-access:'+str(author_id)}) or {}
    authorized=author_id in (int(guild_data.owner_id),505227988229554179) or 'text_commands' in grant.get('permissions',[])
    guild=NS(id=GUILD_ID,owner_id=guild_data.owner_id,get_role=roles.get,get_member=lambda uid:bot_member if uid==me.id else None)
    bot=NS(get_me=lambda:me);role=roles.get(int(action['role_id']))
    if not authorized or not safe_role(role,await protected_roles(db)) or not role_is_manageable(guild,bot,role):
        raise ValueError('This role action is unavailable. Ask staff to review it.')
    target=await rest.fetch_member(GUILD_ID,interaction.user.id)
    events=db.bot_config.database.get_collection('text_command_events',write_concern=WriteConcern(w='majority',wtimeout=10000))
    key='role:'+str(interaction.id)
    from pymongo.errors import DuplicateKeyError
    try:
        await events.insert_one({'_id':key,'guild_id':GUILD_ID,'command':row['command'],'member_id':str(target.id),'role_id':str(role.id),'role_name':role.name,'member_name':getattr(target,'display_name',str(target.id)),'action':action['kind'],'configured_by':str(author_id),'at':datetime.now(timezone.utc),'status':'pending'})
    except DuplicateKeyError:return 'This action was already received.'
    reason='Command '+row['command']+'; self-service; configured by '+str(author_id)
    try:
        if action['kind']=='add_role':
            changed=role.id not in target.role_ids
            if changed:await rest.add_role_to_member(GUILD_ID,target.id,role.id,reason=reason)
            message='Role added: '+role.name
        else:
            changed=role.id in target.role_ids
            if changed:await rest.remove_role_from_member(GUILD_ID,target.id,role.id,reason=reason)
            message='Role removed: '+role.name
    except Exception:
        await events.update_one({'_id':key},{'$set':{'status':'failed'}})
        raise
    await events.update_one({'_id':key},{'$set':{'status':'done','changed':changed}})
    return message
