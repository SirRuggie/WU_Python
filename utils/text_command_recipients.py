"""Per-use recipient selection. Private chooser; one public delivery per invocation."""
import logging
import secrets
from datetime import datetime, timedelta, timezone
import hikari
from hikari.impl import MessageActionRowBuilder as Row
from pymongo import ReturnDocument
from utils.component_state import insert_state
from utils.text_commands import GUILD_ID, FIELDS, collection, validate, fingerprint, payload
from utils.text_command_files import load_files

log = logging.getLogger(__name__)

async def start(event, db, bot, clean):
    token = secrets.token_hex(12)
    await insert_state(db, {'_id':'command-recipient:'+token, 'user_id':int(event.message.author.id),
        'guild_id':GUILD_ID, 'channel_id':int(event.channel_id), 'command':clean['command'],
        'version':fingerprint(clean), 'status':'waiting'}, ttl=timedelta(minutes=10))
    controls = Row().add_interactive_button(hikari.ButtonStyle.PRIMARY, 'cr:open:'+token, label='Choose recipient')
    message = await bot.rest.create_message(event.channel_id,
        content=f"{clean['command']} · Choose a user or role for this reply. Only the person who typed the trigger can choose. Expires in 10 minutes.",
        components=[controls], mentions_everyone=False, user_mentions=False, role_mentions=False)
    await db.component_state.update_one({'_id':'command-recipient:'+token},{'$set':{'prompt_id':int(message.id)}})


def recipient_from(interaction):
    if interaction.component_type != hikari.ComponentType.MENTIONABLE_SELECT_MENU or len(interaction.values)!=1:
        raise ValueError('Choose one user or role.')
    target=int(interaction.values[0])
    resolved=interaction.resolved
    if resolved and target in (resolved.roles or {}):
        role=resolved.roles[target]
        if target==GUILD_ID:raise ValueError('Choose a role other than @everyone.')
        return 'role',target,role
    if resolved and target in (resolved.members or {}):return 'user',target,None
    raise ValueError('Choose a current server member or role.')

async def handle(interaction, db):
    if not interaction.custom_id.startswith('cr:'):return False
    await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_CREATE,flags=hikari.MessageFlag.EPHEMERAL)
    async def tell(text, components=()):
        await interaction.edit_initial_response(content=text,components=list(components),mentions_everyone=False,user_mentions=False,role_mentions=False)
    claimed=False
    state_id=None
    try:
        if interaction.guild_id!=GUILD_ID or not interaction.member or interaction.message.author.id!=interaction.application_id:
            raise ValueError('This picker is not available here.')
        _,step,token=interaction.custom_id.split(':',2)
        if step not in ('open','send') or len(token)!=24 or any(c not in '0123456789abcdef' for c in token):raise ValueError('Run the trigger again.')
        state_id='command-recipient:'+token
        state=await db.component_state.find_one({'_id':state_id})
        if not state:raise ValueError('This picker expired. Run the trigger again.')
        expiry=state['expires_at'].replace(tzinfo=timezone.utc)
        if expiry<=datetime.now(timezone.utc):raise ValueError('This picker expired. Run the trigger again.')
        if int(interaction.user.id)!=state['user_id'] or int(interaction.channel_id)!=state['channel_id'] or state['guild_id']!=GUILD_ID:
            raise ValueError('Only the person who typed this trigger can choose its recipient.')
        if state['status']!='waiting':raise ValueError('This reply was already requested. Check the channel before running it again.')
        if step=='open' and int(interaction.message.id)!=state.get('prompt_id'):raise ValueError('Run the trigger again.')
        row=await collection(db).find_one({'_id':f'{GUILD_ID}:{state["command"]}','enabled':True})
        if not row:raise ValueError('This trigger is turned off or removed.')
        clean=validate({key:row[key] for key in FIELDS if key in row})
        if not clean['choose_recipient'] or fingerprint(clean)!=state['version']:raise ValueError('This trigger changed. Run it again.')
        if step=='open':
            menu=Row().add_select_menu(hikari.ComponentType.MENTIONABLE_SELECT_MENU,'cr:send:'+token,placeholder='Choose a user or role',min_values=1,max_values=1)
            await tell('Choose who this reply is for. Selecting sends it to the original channel.'+' The selected recipient will be pinged inside the message card.'+(' Saved message pings are also enabled.' if clean['allow_pings'] else ''),[menu])
            return True
        kind,target,role=recipient_from(interaction)
        if role and not role.is_mentionable and not interaction.member.permissions & hikari.Permissions.MENTION_ROLES:
            raise ValueError('You cannot ping this role. Choose a mentionable role or ask staff.')
        data=payload(clean,await load_files(db,clean),recipient=(kind,target))
        claimed=bool(await db.component_state.find_one_and_update({'_id':state_id,'status':'waiting','expires_at':{'$gt':datetime.now(timezone.utc)}},{'$set':{'status':'sending','recipient_id':target,'recipient_kind':kind}},return_document=ReturnDocument.AFTER))
        if not claimed:raise ValueError('This reply was already requested. Check the channel.')
        message=await interaction.app.rest.create_message(state['channel_id'],**data)
        await db.component_state.update_one({'_id':state_id},{'$set':{'status':'sent','message_id':int(message.id)}})
        await tell('Reply sent to this channel.')
        try:
            await interaction.app.rest.edit_message(state['channel_id'],state['prompt_id'],content=f"{clean['command']} · Reply sent.",components=[],mentions_everyone=False,user_mentions=False,role_mentions=False)
        except Exception:log.warning('Could not clear recipient prompt',exc_info=True)
    except ValueError as exc:await tell(str(exc))
    except Exception:
        log.exception('Recipient trigger failed')
        # Never automatically retry an uncertain send: it could duplicate a ping.
        await tell('Could not confirm delivery. Check the channel before running this trigger again.' if claimed else 'Could not open or send this reply. Try again shortly.')
    return True
