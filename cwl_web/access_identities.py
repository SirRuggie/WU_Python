"""Read-only Discord identity decoration for owner access lists."""
import asyncio
from aiohttp import ClientError, web


async def decorate_access(request, data):
    from .server_management import discord, GUILD_ID
    from .manage_roles import member_option
    limit = asyncio.Semaphore(5)
    roles = None
    if any(row['kind'] == 'role' for row in data['grants']):
        try:
            roles = await asyncio.wait_for(discord(request, 'GET', f'/guilds/{GUILD_ID}/roles'), timeout=5)
        except (web.HTTPException, ClientError, TimeoutError):
            pass

    async def resolve(grant):
        row = dict(grant, identity_status='unavailable')
        try:
            if grant['kind'] == 'role':
                role = next((role for role in roles or [] if str(role['id']) == grant['id']), None)
                if role:
                    row.update(display_name=role['name'], identity_status='current')
                elif roles is not None:
                    row['identity_status'] = 'missing'
            else:
                async with limit:
                    member = await asyncio.wait_for(discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{grant["id"]}'), timeout=5)
                user = member.get('user', {})
                name = member.get('nick') or user.get('global_name') or user.get('username')
                if name:
                    identity = member_option(dict(member, user=dict(user, id=grant['id'])))
                    row.update(display_name=name, username=user.get('username'),
                               avatar_url=identity['avatar_url'], identity_status='current')
        except web.HTTPNotFound:
            row['identity_status'] = 'missing'
        except (web.HTTPException, ClientError, TimeoutError):
            pass
        return row

    # Keep the owner ID allowlist unchanged. Decoration is presentation only;
    # owner identities never become editable grant entries or stored authority.
    grants, owners = await asyncio.gather(
        asyncio.gather(*(resolve(row) for row in data['grants'])),
        asyncio.gather(*(resolve({'kind': 'user', 'id': owner, 'label': owner})
                         for owner in data.get('owners', []))),
    )
    return dict(data, grants=grants, owner_identities=owners)
