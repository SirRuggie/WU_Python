"""One explicit recruiter review of the exact conflicting link identities."""
from datetime import timedelta
import uuid

import hikari
import lightbulb
from hikari.impl import ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text
from hikari.impl import MessageActionRowBuilder as Row, InteractiveButtonBuilder as Button
from hikari.impl import ModalActionRowBuilder

from extensions.components import register_action
from extensions.commands.tickets import account_sync, perms, store
from utils.component_state import insert_state, get_state
from utils.mongo import MongoClient

REASON = 'linked_account_conflict_review'


async def prompt(mongo, ticket, owner_id, guild_id, *, overturn=False):
    linked = ticket.get('linked_accounts') or {}
    token = uuid.uuid4().hex
    await insert_state(mongo, {'_id':token, 'type':'ticket_link_review',
        'owner_id':int(owner_id),'guild_id':int(guild_id),'ticket_id':ticket['_id'],
        'user_id':int(ticket['user_id']),'conflict_key':linked.get('conflict_key'),
        'conflicting_tags':list(linked.get('conflicting_tags') or []),
        'ticket_rev':int(ticket.get('rev') or 0), 'status':ticket.get('status'), 'overturn':overturn}, ttl=timedelta(minutes=15))
    tags=', '.join(linked.get('conflicting_tags') or [])
    return [Container(accent_color=0xF1C40F,components=[
        Text(content='## Review linked-account conflicts\nHave you reviewed these linked-account conflicts?'),
        Text(content=f'**Accounts:** {tags}\nYes opens a reason form covering all these accounts. External links and existing flags will not be changed.'),
        Row(components=[Button(style=hikari.ButtonStyle.SECONDARY,label='Yes — Reviewed',custom_id=f'ticket_link_review_yes:{token}'),
            Button(style=hikari.ButtonStyle.SECONDARY,label='No — Review First',custom_id=f'ticket_link_review_no:{token}')]),
    ])]


async def session(ctx, mongo, token):
    data=await get_state(mongo,token)
    if not data or data.get('type')!='ticket_link_review': return None
    if data.get('owner_id')!=int(ctx.user.id) or data.get('guild_id')!=int(ctx.guild_id or 0): return None
    if not await perms.is_recruiter(getattr(ctx,'member',None),mongo): return None
    return data


@register_action('ticket_link_review_yes',opens_modal=True,no_return=True,preload_state=False)
@lightbulb.di.with_di
async def yes(ctx,action_id:str,mongo:MongoClient=lightbulb.di.INJECTED,**_):
    if not await session(ctx,mongo,action_id):
        await ctx.respond('This review expired or is not yours. Click Approve again.',ephemeral=True)
        return
    await ctx.respond_with_modal(title='Linked-account review',custom_id=f'ticket_link_review_submit:{action_id}',components=[
        ModalActionRowBuilder().add_text_input('reason','Why can these accounts be accepted?',style=hikari.TextInputStyle.PARAGRAPH,required=True,min_length=5,max_length=1000,
            placeholder='Old Discord account; source linking tools unavailable. I reviewed all listed accounts.')])


@register_action('ticket_link_review_no',opens_modal=True,no_return=True,preload_state=False)
@lightbulb.di.with_di
async def no(ctx,action_id:str,mongo:MongoClient=lightbulb.di.INJECTED,**_):
    await ctx.defer(ephemeral=True)
    data=await session(ctx,mongo,action_id)
    if not data:
        await ctx.interaction.edit_initial_response(content='This review expired or is not yours. Click Approve again.')
        return
    await ctx.interaction.edit_initial_response(components=[Container(accent_color=0xF1C40F,components=[
        Text(content='## Review first\nReview and resolve the linked-account conflicts, or click Approve again when you are ready to record your reasoning. Nothing was changed.'),
        Row(components=[Button(style=hikari.ButtonStyle.SECONDARY,label='Review Player Info',custom_id=f"ticket_player_info:{data['ticket_id']}|1")]),
    ])])


async def save_review(mongo, data, *, reason, actor_id, actor_name):
    """CAS against current conflict identities and ticket decision revision."""
    reason=reason.strip()
    if not 5<=len(reason)<=1000 or not data.get('conflict_key'): return False
    ticket=await store.find_one(mongo,{'_id':data['ticket_id'],**store.RUNTIME_FILTER})
    if not ticket or ticket.get('user_id')!=data['user_id'] or ticket.get('status')!=data['status'] or int(ticket.get('rev') or 0)!=data['ticket_rev']: return False
    linked=ticket.get('linked_accounts') or {}
    if linked.get('conflict_key')!=data['conflict_key'] or sorted(linked.get('conflicting_tags') or [])!=sorted(data['conflicting_tags']) or linked.get('unavailable_sources'): return False
    prior=linked.get('conflict_review') or {}
    if prior.get('conflict_key')==data['conflict_key']: return False
    revision=int(linked.get('revision') or 0)
    review={'conflict_key':data['conflict_key'],'tags':data['conflicting_tags'],'user_id':data['user_id'],
        'reason':reason,'reviewed_by':int(actor_id),'reviewed_by_name':actor_name,'reviewed_at':store.utcnow()}
    result=await store.compare_and_swap_linked_accounts(mongo,ticket['_id'],expected_revision=revision,
        update={'$set':{'linked_accounts.conflict_review':review,'linked_accounts.revision':revision+1,'linked_accounts.fetched_at':review['reviewed_at']},
            '$push':{'account_identity_audit':{'$each':[{'event':'linked_account_conflicts_reviewed',**review}], '$slice':-store.MAX_AUDIT_ENTRIES}}},
        fetched_at=review["reviewed_at"],expected_ticket_revision=data["ticket_rev"],expected_status=data["status"])
    return result.won


@register_action('ticket_link_review_submit',is_modal=True,no_return=True,preload_state=False)
@lightbulb.di.with_di
async def submit(ctx,action_id:str,mongo:MongoClient=lightbulb.di.INJECTED,bot:hikari.GatewayBot=lightbulb.di.INJECTED,**_):
    await ctx.defer(ephemeral=True)
    data=await session(ctx,mongo,action_id)
    from extensions.commands.tickets import console, resolve
    if not data or not await save_review(mongo,data,reason=console._modal_value(ctx,'reason'),actor_id=ctx.user.id,actor_name=ctx.user.username):
        await ctx.interaction.edit_initial_response(content='The review expired, was already submitted, or the ticket/accounts changed. Click Approve again to review the latest information.')
        return
    if data.get('overturn'):
        result=await resolve.overturn_ticket(bot,mongo,ticket_id=data['ticket_id'],member=ctx.member,actor_name=ctx.user.username,to_status='approved')
    else:
        result=await resolve.approve_ticket(bot,mongo,ticket_id=data['ticket_id'],member=ctx.member,actor_name=ctx.user.username)
    if result.outcome in {store.WON,store.EFFECT_FAILED}:
        await console.request_hub_refresh_best_effort(bot,mongo,reason='reviewed link conflicts and approved')
    view=await console._transition_result_panel(result,verb='approved',mongo=mongo,owner_id=int(ctx.user.id),guild_id=int(ctx.guild_id))
    await ctx.interaction.edit_initial_response(components=view,user_mentions=False,role_mentions=False,mentions_everyone=False)
