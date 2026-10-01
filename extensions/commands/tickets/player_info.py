"""Staff-only combined player information and refresh controls."""
import asyncio

import hikari
import lightbulb
from hikari.impl import ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text
from hikari.impl import MessageActionRowBuilder as Row, InteractiveButtonBuilder as Button

from extensions.components import register_action
from extensions.commands.tickets import account_sync, perms, store
from utils.mongo import MongoClient

_refresh_locks = {}


def account_line(account):
    from extensions.commands.accounts import _escape_markdown
    name = _escape_markdown(account.name or 'Profile unavailable', max_raw_length=50)
    clan = _escape_markdown(account.clan_name or 'No clan', max_raw_length=40)
    source = ' + '.join(account.link_sources) or 'Previously recorded'
    verification = ''
    if 'ClashPerk' in account.link_sources:
        verification = ' · CP verified' if account.clashperk_verified else ' · CP unverified'
    details = f'TH{account.town_hall} · {clan}' if account.profile_status == 'loaded' else 'Player profile unavailable'
    return f'**{name}** · `{account.tag}`\n{details}\n{source}{verification}'


def warnings(snapshot):
    lines = []
    if snapshot.unavailable_sources:
        lines.append('⚠️ Lookup incomplete: ' + ', '.join(snapshot.unavailable_sources) + ' unavailable. Previously recorded accounts may be stale.')
    if snapshot.conflicting_tags:
        lines.append('⚠️ Conflicting link ownership: ' + ', '.join(snapshot.conflicting_tags[:10]) + '. Resolve the links before approval.')
    return '\n'.join(lines)


def review_note(ticket):
    from extensions.commands.accounts import _escape_markdown
    linked = ticket.get('linked_accounts') or {}
    review = linked.get('conflict_review') or {}
    if not review or review.get('conflict_key') != linked.get('conflict_key') or linked.get('conflicting_tags'):
        return ''
    return ('**Staff-reviewed link conflicts:** ' + ', '.join(review.get('tags') or [])
        + '\n**Reason:** ' + _escape_markdown(review.get('reason'), max_raw_length=300))


def panel(ticket, page=1):
    snapshot = account_sync.snapshot_from_ticket(ticket)
    accounts = snapshot.current_accounts
    pages = max(1, (len(accounts) + 7) // 8)
    page = min(pages, max(1, page))
    content = '\n\n'.join(account_line(a) for a in accounts[(page-1)*8:page*8]) or 'No linked accounts found.'
    ticket_id = str(ticket['_id'])
    controls = [Button(style=hikari.ButtonStyle.SECONDARY, label='Refresh Player Info', custom_id=f'ticket_player_refresh:{ticket_id}')]
    for label, target, disabled in [('Previous', page-1, page==1), ('Next',page+1,page==pages)]:
        controls.append(Button(style=hikari.ButtonStyle.SECONDARY,label=label,custom_id=f'ticket_player_info:{ticket_id}|{target}',is_disabled=disabled))
    return [Container(accent_color=0x3498DB,components=[
        Text(content=f'## Linked Player Information · {len(accounts)} accounts'),
        Text(content=('\n\n'.join(p for p in (warnings(snapshot),review_note(ticket),content) if p)).strip()),
        Text(content=f'Page {page}/{pages} · Sources: ClashKing and ClashPerk'),
        Row(components=controls),
    ])]


async def _get_ticket(ctx, mongo, ticket_id):
    if not await perms.is_recruiter(getattr(ctx,'member',None),mongo):
        return None
    return await store.find_one(mongo, {'_id':ticket_id, **store.RUNTIME_FILTER})


@register_action('ticket_player_info', opens_modal=True, preload_state=False, no_return=True)
@lightbulb.di.with_di
async def show(ctx, action_id: str, mongo: MongoClient=lightbulb.di.INJECTED, **_):
    await ctx.defer(ephemeral=True)
    ticket_id, _, page = action_id.partition('|')
    ticket = await _get_ticket(ctx,mongo,ticket_id)
    if ticket is None:
        await ctx.interaction.edit_initial_response(content='Recruiter access and an existing ticket are required.')
        return
    await ctx.interaction.edit_initial_response(components=panel(ticket,int(page) if page.isdigit() else 1),user_mentions=False,role_mentions=False,mentions_everyone=False)


@register_action('ticket_player_refresh', opens_modal=True, preload_state=False, no_return=True)
@lightbulb.di.with_di
async def refresh(ctx, action_id: str, mongo: MongoClient=lightbulb.di.INJECTED, bot: hikari.GatewayBot=lightbulb.di.INJECTED, **_):
    await ctx.defer(ephemeral=True)
    ticket = await _get_ticket(ctx,mongo,action_id)
    if ticket is None:
        await ctx.interaction.edit_initial_response(content='Recruiter access and an existing ticket are required.')
        return
    client = account_sync.configured_coc_client()
    if client is None:
        await ctx.interaction.edit_initial_response(content='Player service is starting. Please retry shortly.')
        return
    lock = _refresh_locks.setdefault(action_id,asyncio.Lock())
    if lock.locked():
        await ctx.interaction.edit_initial_response(content='A player refresh is already running for this ticket.')
        return
    try:
        async with lock:
            result = await account_sync.sync_ticket_accounts(mongo,client,action_id,source=account_sync.SOURCE_RECRUITER_REFRESH)
            if result.ticket is None:
                await ctx.interaction.edit_initial_response(content='Ticket no longer exists.')
                return
            from extensions.commands.tickets.resolve import _queue_and_deliver_latest_staff_context
            delivered = await _queue_and_deliver_latest_staff_context(bot,mongo,result.ticket,result.snapshot)
            await ctx.interaction.edit_initial_response(components=panel(result.ticket),content=None if delivered else 'Staff summary update is pending; the saved account lookup is shown below.',user_mentions=False,role_mentions=False,mentions_everyone=False)
    finally:
        if not lock.locked():
            _refresh_locks.pop(action_id,None)
