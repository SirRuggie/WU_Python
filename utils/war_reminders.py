"""War reminder settings, selection, and standard Discord message rendering."""
from datetime import datetime, timedelta, timezone
from utils.town_halls import town_hall_emoji
from utils.dashboard_urls import TASKS_URL, WARS_URL

import re

GUILD_ID = 644963518025826315
DEFAULTS = dict(enabled=False, channel_id='', war_started=True, minutes=[720, 480, 60], audience='remaining')


def settings(row=None):
    values = {key: (row or {}).get(key, default) for key, default in DEFAULTS.items()}
    # Callers may edit their form values without changing defaults or DB records.
    values['minutes'] = list(values['minutes'])
    return values


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Check the reminder settings.')
    if type(value['enabled']) is not bool or type(value['war_started']) is not bool:
        raise ValueError('Choose whether reminders and war-start notices are enabled.')
    if not isinstance(value['channel_id'], str) or (value['channel_id'] and not re.fullmatch(r'[0-9]{15,22}', value['channel_id'])):
        raise ValueError('Choose a Discord channel.')
    if value['enabled'] and not value['channel_id']:
        raise ValueError('Select a channel before turning reminders on.')
    minutes = value['minutes']
    if not isinstance(minutes, list) or len(minutes) > 1440 or any(type(n) is not int or not 1 <= n <= 1440 for n in minutes):
        raise ValueError('Use whole minutes from 1 to 1440 (24 hours).')
    if value['enabled'] and not minutes and not value['war_started']:
        raise ValueError('Add a reminder time or turn on the war-start notice.')
    if value['audience'] not in ('remaining', 'zero'):
        raise ValueError('Choose players with attacks remaining or no attacks used.')
    return {**value, 'minutes': sorted(set(minutes), reverse=True)}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def snapshot(war, clan_tag):
    if war is None or war.state != 'inWar':
        return None
    side = war.clan if war.clan.tag == clan_tag else war.opponent
    opponent = war.opponent if side is war.clan else war.clan
    if side.tag != clan_tag:
        raise ValueError('War does not contain the selected clan.')
    limit = war.attacks_per_member
    if type(limit) is not int or limit < 1:
        raise ValueError('War attack allowance is unavailable.')
    members = sorted(side.members, key=lambda m: m.map_position)
    if len(members) != war.team_size:
        raise ValueError('War roster is incomplete.')
    return dict(start=utc(war.start_time.time), end=utc(war.end_time.time), name=side.name,
                opponent=opponent.name, tag=clan_tag, limit=limit,
                members=[dict(tag=m.tag, name=m.name, position=m.map_position,
                              th=m.town_hall, used=len(m.attacks)) for m in members])


def due(war, config, now):
    """Only send within five minutes of a threshold; never replay stale reminders."""
    if not config['enabled'] or not war or not war['start'] <= now < war['end']:
        return []
    events = [('start', war['start'])] if config['war_started'] else []
    events += [(str(n), war['end'] - timedelta(minutes=n)) for n in config['minutes']]
    return [key for key, at in events if war['start'] <= at and 0 <= (now-at).total_seconds() < 300]


def war_identity(value):
    """Compare the persisted war start at existing BSON-millisecond precision."""
    value = utc(value)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def catchup_events(war, config, now, maintenance_since, prior_war_start):
    """Existing occurrence identities missed in this observed maintenance window.

    The prior stored war identity, not the freshly overwritten status, is the
    authority. Unknown or different wars never acquire catch-up receipts.
    """
    if (not war or not config['enabled'] or maintenance_since is None
            or prior_war_start is None or war_identity(prior_war_start) != war_identity(war['start'])
            or not war['start'] <= now < war['end']):
        return []
    since = utc(maintenance_since) - timedelta(seconds=60)
    events = [('start', war['start'])] if config['war_started'] else []
    events += [(str(n), war['end'] - timedelta(minutes=n)) for n in config['minutes']]
    return sorted([(key, at) for key, at in events
                   if war['start'] <= at and since <= at < now - timedelta(seconds=300)],
                  key=lambda item: (item[1], item[0]))


def catchup_boundary(war, config, now, maintenance_since, prior_war_start):
    """Retain the window for a threshold exactly300s old until the next scan.

    Normal due() is strictly <300s and the approved missed window is strictly
    >300s. Moving only this pure cutoff one microsecond identifies that boundary;
    it does not authorize sending there or schedule another provider request.
    """
    return any(at == now - timedelta(seconds=300) for _, at in catchup_events(
        war, config, now + timedelta(microseconds=1), maintenance_since, prior_war_start))


def pending(war, audience):
    return [m for m in war['members'] if m['used'] < war['limit'] and (audience != 'zero' or m['used'] == 0)]


def clean(value):
    # Keep external names on one row; truncate before escaping so a trailing
    # backslash cannot consume our own closing Markdown delimiters.
    plain = re.sub(r'[\x00-\x1f\x7f\u2028\u2029\u202a-\u202e\u2066-\u2069]', ' ', str(value))[:100]
    return re.sub(r'([\\`*_~|<>\[\]@])', r'\\\1', plain)


def duration(minutes):
    hours, minutes = divmod(minutes, 60)
    return ' '.join(text for text in (
        f"{hours} hour{'s' if hours != 1 else ''}" if hours else '',
        f"{minutes} minute{'s' if minutes != 1 else ''}" if minutes else '') if text)


def discord_length(text):
    return len(text.encode('utf-16-le')) // 2


def messages(war, config, event, owners=None, *, test=False, tester=None, sample_label="Sample players", sample_group="Sample accounts", delayed_at=None):
    """One line per single-account owner; multi-account owners get one mention
    and a quoted row per account. Pages split safely without repeat pings."""
    members = pending(war, config['audience'])
    if not members and not test:
        return []
    owners = owners or {}
    groups = {}
    for member in members:
        uid = str(tester or '') if test else str(owners.get(member['tag']) or '')
        uid = uid if re.fullmatch(r'[0-9]{15,22}', uid) else ''
        if test:
            uid = '' if member.get('sample_unlinked') else (uid or 'sample')
        groups.setdefault(uid, []).append(member)
    unlinked = groups.pop('', [])
    singles = [(uid, accounts) for uid, accounts in groups.items() if len(accounts) == 1 and uid != 'sample']
    multis = [(uid, accounts) for uid, accounts in groups.items() if len(accounts) > 1 or uid == 'sample']

    def account(member, tag=False):
        emoji = town_hall_emoji(member["th"]) or f"TH{member['th']}"
        text = f"{emoji} **{clean(member['name'])}**"
        if tag:
            text += f" `{re.sub(r'[^#A-Z0-9]', '', str(member['tag']).upper())[:24]}`"
        # Non-breaking spaces keep the count next to its separator on phones.
        return text + f" ·\u00a0{member['used']}/{war['limit']}"

    if delayed_at is not None:
        seconds = max(0, (war['end'] - delayed_at).total_seconds())
        label = (duration(int(seconds // 60)) + ' left' if seconds >= 60
                 else 'Less than a minute left') + ' · delayed by Clash maintenance'
    else:
        label = 'War started' if event == 'start' else duration(int(event))+' left'
    started = event == 'start' and delayed_at is None
    icon = '⚔️' if started else '🔔'
    title = f"{clean(war['name'])} vs {clean(war['opponent'])} · {label}"
    end = int(war['end'].timestamp())
    remaining = sum(war['limit']-m['used'] for m in members)
    count = f"{len(members)} account{'s' if len(members) != 1 else ''}"
    subline = (f"-# Ends <t:{end}:t> (<t:{end}:R>) · "
               f"{remaining} attacks left on {count} · Attacks used / available")
    if test:
        subline += f'\n-# Test reminder · {sample_label} · Simulated attacks'

    def head(part, first):
        # Concatenate: clan names may contain braces, so never str.format them.
        heading = f'## {icon} {title}{part}' if first else f'{icon} **{title}{part}**'
        return heading+'\n'+(subline+'\n' if first else '')+'\n'

    longest_part = ' · part 99 of 99'
    first_budget = 2000 - discord_length(head(longest_part, True))
    later_budget = 2000 - discord_length(head(longest_part, False))

    # Blocks never carry a second mention: an oversized group continues unpinged.
    blocks = [(f"<@{uid}> {account(accounts[0])}", [uid]) for uid, accounts in singles]
    for uid, accounts in multis:
        heading = f'**{sample_group}**' if uid == 'sample' else f'<@{uid}> · {len(accounts)} accounts'
        blocks.extend(_grouped(heading, [uid] if uid != 'sample' else [], ['> '+account(m) for m in accounts], first_budget))
    if unlinked:
        blocks.extend(_grouped('-# Not linked · no ping', [], ['> '+account(m, tag=True) for m in unlinked], first_budget))
    if not blocks:
        blocks = [('All attacks are complete!', [])]

    pages, text, users = [], '', []
    for block, mentions in blocks:
        candidate = text+'\n'+block if text else block
        if text and discord_length(candidate) > (later_budget if pages else first_budget):
            pages.append((text, users))
            text, users = block, list(mentions)
        else:
            text, users = candidate, users+mentions
    pages.append((text, users))
    total = len(pages)
    results = []
    for index, (text, users) in enumerate(pages):
        part = f' · part {index+1} of {total}' if total > 1 else ''
        results.append(dict(content=head(part, index == 0)+text, footer=index == total-1,
                            allowed_mentions=dict(parse=[], users=users, roles=[], replied_user=False),
                            components=[{"type": 1, "components": [
                                {"type": 2, "style": 5, "label": "My tasks", "url": TASKS_URL},
                                {"type": 2, "style": 5, "label": "Wars", "url": WARS_URL},
                            ]}]))
    return results


def _grouped(heading, mentions, rows, budget):
    """Split one owner's rows into blocks; only the first block can mention."""
    blocks, text, users = [], heading, list(mentions)
    for row in rows:
        if discord_length(text+'\n'+row) > budget:
            blocks.append((text, users))
            text, users = '**Accounts continued**', []
        text += '\n'+row
    blocks.append((text, users))
    return blocks


def sample(clan, event):
    now = datetime.now(timezone.utc)
    minutes = 1440 if event == 'start' else int(event)
    return dict(start=now, end=now+timedelta(minutes=minutes), name=clan['name'], tag=clan['tag'], opponent='Rival Clan', limit=2,
                members=[dict(tag='#SAMPLE1', name='Shield Bearer', position=1, th=18, used=0),
                         dict(tag='#SAMPLE2', name='Night Archer', position=7, th=17, used=1),
                         dict(tag='#SAMPLE3', name='Iron Guardian', position=12, th=16, used=0, sample_unlinked=True)])

COPY_FIELDS = frozenset({'minutes', 'audience', 'war_started', 'enabled'})


def copied_settings(source, target, fields):
    """Copy selected behavior, keeping each destination's own channel."""
    if not isinstance(fields, list) or not fields or any(
        not isinstance(field, str) or field not in COPY_FIELDS for field in fields
    ) or len(fields) != len(set(fields)):
        raise ValueError('Choose reminder fields to copy. Channels cannot be copied.')
    result = settings(target)
    source = settings(source)
    for field in fields:
        result[field] = source[field]
    if not result['channel_id']:
        result['enabled'] = False
    return validate(result)
