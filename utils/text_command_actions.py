"""Revision-checked private saved replies for persistent command controls."""
import logging
import hikari
from utils.text_commands import GUILD_ID,FIELDS,collection,validate,payload,fingerprint,walk_blocks
from utils.text_command_files import load_files
log=logging.getLogger(__name__)

def actions(row):
    for path,block in walk_blocks(row.get('blocks',[])):
        if block['type']=='actions':
            for index,item in enumerate(block['buttons']):yield path+'.'+str(index),item['action']
        elif block['type']=='select':
            for index,item in enumerate(block['options']):yield path+'@'+str(index),item['action']

async def handle(interaction,db):
    if not interaction.custom_id.startswith('ct:'):return False
    await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_CREATE,flags=hikari.MessageFlag.EPHEMERAL)
    async def tell(message):
        await interaction.edit_initial_response(content=message,mentions_everyone=False,user_mentions=False,role_mentions=False)
    try:
        if interaction.guild_id!=GUILD_ID or not interaction.member or interaction.message.author.id!=interaction.application_id:
            await tell('This control is not available here.');return True
        _,name,version,path=interaction.custom_id.split(':',3)
        row=await collection(db).find_one({'_id':f'{GUILD_ID}:{name}','enabled':True})
        if not row:
            await tell('This command is turned off or removed.');return True
        clean=validate({key:row[key] for key in FIELDS if key in row})
        if fingerprint(clean)!=version:
            await tell('This message is out of date. Run the command again.');return True
        if interaction.component_type==hikari.ComponentType.TEXT_SELECT_MENU:
            if len(interaction.values)!=1:raise ValueError('Choose one option.')
            path+='@'+interaction.values[0]
        action=dict(actions(clean)).get(path)
        if not action:raise ValueError('This option is no longer available.')
        if action['kind']!='reply':
            from utils.text_command_roles import perform
            await tell(await perform(interaction,db,row,action));return True
        target=await collection(db).find_one({'_id':f'{GUILD_ID}:{action["command"]}','enabled':True})
        if not target:raise ValueError('That reply is currently unavailable.')
        reply=validate({key:target[key] for key in FIELDS if key in target})
        if reply.get('choose_recipient'):
            await tell(f'Type {reply["command"]} in the channel to choose a user or role for this reply.');return True
        data=payload(reply,await load_files(db,reply))
        data.update(flags=hikari.MessageFlag.IS_COMPONENTS_V2|hikari.MessageFlag.EPHEMERAL,mentions_everyone=False,user_mentions=False,role_mentions=False)
        await interaction.execute(**data)
        await interaction.delete_initial_response()
    except ValueError as exc:await tell(str(exc))
    except Exception:
        log.exception('Command action failed')
        await tell('Could not complete this action. Try again or ask staff.')
    return True
