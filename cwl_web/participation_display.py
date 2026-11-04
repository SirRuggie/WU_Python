"""Read existing capture evidence and decorate outgoing participation copies.

Keep this outside policy views: bonus fingerprints and stored receipts use the
original source fields, never these presentation fields.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json

from utils.cwl_participation_status import (
    ParticipationEvidence, effective_participation_status,
)


def _recent(stamp, now):
    try:
        age = (now - datetime.fromisoformat(stamp)).total_seconds()
        return 0 <= age <= 30 * 60
    except (TypeError, ValueError):
        return False


def participation_evidence(db, season_id, cycle, *, now=None, accounts=()):
    """One season-wide read, with no writes or per-account queries."""
    now = now or datetime.now(timezone.utc)
    settings = db.execute(
        'SELECT last_checked_at FROM participation_sync_settings WHERE season_id=? AND cycle=?',
        (season_id, cycle),
    ).fetchone()
    checked = settings['last_checked_at'] if settings else None
    recent = _recent(checked, now)
    groups = db.execute(
        'SELECT clan_tag,state,war_tags_json,observed_at FROM participation_group_observations '
        'WHERE season_id=? AND cycle=?', (season_id, cycle),
    ).fetchall()
    wars = {}
    for row in db.execute(
        'SELECT war_tag,clan_tag,state,ended,observed_at FROM participation_war_observations '
        'WHERE season_id=? AND cycle=?', (season_id, cycle),
    ):
        wars[(row['war_tag'], row['clan_tag'])] = row
    fetches = {row['war_tag']: row for row in db.execute(
        'SELECT war_tag,ended,scanned_clans_json,observed_at FROM participation_war_fetches '
        'WHERE season_id=? AND cycle=?', (season_id, cycle),
    )}
    captured = {row[0] for row in db.execute(
        'SELECT war_tag FROM bonus_allowance_wars WHERE season_id=? AND cycle=?',
        (season_id, cycle),
    )}
    result = {}
    for group in groups:
        clan = group['clan_tag']
        group_current = recent and group['observed_at'] == checked
        active_current = True
        final_usable = True
        failure = 'group_unavailable' if recent and not group_current else None
        round_number = None
        for number, tags in enumerate(json.loads(group['war_tags_json']), 1):
            own_tags = [tag for tag in tags if (tag, clan) in wars]
            # Group rounds contain every clan's war. Once our side is known,
            # another clan's failed war must not mark this clan as failed.
            for tag in own_tags or tags:
                if tag == '#0':
                    continue
                war = wars.get((tag, clan))
                fetched = fetches.get(tag)
                if war and war['state'] in ('WAR', 'ENDED'):
                    round_number = max(round_number or 0, number)
                sealed = bool(
                    fetched and fetched['ended'] and tag in captured
                    and clan in json.loads(fetched['scanned_clans_json'])
                )
                if war and war['ended']:
                    if group_current and fetched and fetched['observed_at'] == checked and not fetched['ended']:
                        failure = 'war_state_regression'
                        active_current = False
                    final_usable = final_usable and (sealed or war['observed_at'] == checked)
                    continue
                # A fresh fetch without our side belongs to another group clan.
                fresh_fetch = bool(
                    fetched and fetched['observed_at'] == checked
                    and (war is None or war['observed_at'] == checked)
                )
                if sealed and war is None:
                    continue
                active_current = active_current and fresh_fetch
                if group_current and not fresh_fetch:
                    failure = 'war_unavailable'
        result[clan] = ParticipationEvidence(
            group_state=group['state'], group_current=group_current,
            active_wars_current=recent and active_current,
            finalized_wars_usable=final_usable,
            round_number=round_number, failure_reason=failure,
        )
    # A matching captured account can confirm an initial group failure even
    # when no group observation has ever been saved. A new/unchecked signup
    # cannot borrow that failure from another account's capture.
    for account in accounts:
        clan = account.get('assigned_clan_tag')
        if clan and clan not in result and account.get('source_status') in ('stale', 'unavailable'):
            result[clan] = ParticipationEvidence(
                failure_reason='group_unavailable' if recent else None,
            )
    return result


def decorate_participation_accounts(accounts, evidence, *, sync_status=None):
    """Return copies; callers keep raw source fields for all decisions."""
    result = deepcopy(accounts)
    for account in result:
        account['display_status'] = effective_participation_status(
            account.get('source_status'), complete=account.get('source_complete', False),
            has_results=(account.get('source_attacks') is not None
                         or account.get('source_stars') is not None),
            evidence=evidence.get(account.get('assigned_clan_tag'), ParticipationEvidence()),
            sync_status=sync_status,
        )
    return result


def decorate_participation_payload(db, season_id, payload, *, now=None):
    """Decorate a final response, never an internal policy/fingerprint view."""
    from .participation_sync import settings_view

    cycle = (payload.get('cycle') or (payload.get('sync') or {}).get('cycle')
             or (payload.get('summary') or {}).get('cwl_month'))
    cycle = cycle or settings_view(db, season_id)['cycle']
    sync_status = (payload.get('sync') or {}).get('status')

    def participation_account(value):
        # Weight sources use source_status too; only participation DTOs own
        # source_complete. Accounts exports carry these fields with a prefix.
        return 'tag' in value and 'source_status' in value and 'source_complete' in value

    def export_account(value):
        if value.get('participation_source_status') is None:
            return None
        account = {key.removeprefix('participation_'): item for key, item in value.items()
                   if key.startswith('participation_')}
        account.update(tag=value.get('tag'), assigned_clan_tag=value.get('assigned_clan_tag'))
        return account

    def collect(value, inherited_cycle):
        if isinstance(value, list):
            return [account for item in value for account in collect(item, inherited_cycle)]
        if isinstance(value, dict):
            own_cycle = value.get('cycle') or inherited_cycle
            found = [value] if own_cycle == cycle and participation_account(value) else []
            exported = export_account(value)
            if own_cycle == cycle and exported:
                found.append(exported)
            return found + [account for item in value.values() for account in collect(item, own_cycle)]
        return []

    evidence = participation_evidence(db, season_id, cycle, now=now,
                                      accounts=collect(payload, cycle))
    def visit(value, inherited_cycle):
        if isinstance(value, list):
            return [visit(item, inherited_cycle) for item in value]
        if isinstance(value, dict):
            own_cycle = value.get('cycle') or inherited_cycle
            # Rebuild each path separately. deepcopy's alias preservation would
            # let a historical path overwrite the current account's status.
            result = {key: visit(item, own_cycle) for key, item in value.items()
                      if key != 'display_status'}
            if participation_account(value):
                # Saved draws from another month must not borrow today's check.
                facts = evidence if own_cycle == cycle else {}
                result = decorate_participation_accounts(
                    [result], facts, sync_status=sync_status if own_cycle == cycle else None,
                )[0]
            exported = export_account(result)
            if exported:
                facts = evidence if own_cycle == cycle else {}
                result['participation_display_status'] = decorate_participation_accounts(
                    [exported], facts, sync_status=sync_status if own_cycle == cycle else None,
                )[0]['display_status']
            if isinstance(result.get('selected'), list) and isinstance(result.get('warnings'), list):
                # Keep the manual preview's reason/acknowledgement decision and
                # warning count. Only its generated status words change here,
                # after the original fingerprint and policy calculations.
                replacements = {}
                for account in result['selected']:
                    if not isinstance(account, dict) or 'display_status' not in account:
                        continue
                    prefix = f"{account['tag']} {account['player_name']}: {account.get('eligibility_reason')}; "
                    raw = prefix + f"source {account.get('source_status')} / {'complete' if account.get('source_complete') else 'incomplete'}"
                    replacements[raw] = prefix + account['display_status']['label']
                result['warnings'] = [replacements.get(warning, warning) if isinstance(warning, str) else warning
                                      for warning in result['warnings']]
            return result
        return deepcopy(value)

    return visit(payload, cycle)


def participation_json_response(request, payload, *, db=None):
    """HTTP boundary after all policy, receipt and fingerprint calculations."""
    from aiohttp import web
    from .app import _sid, _store

    sid = _sid(request)
    if db is not None:
        result = decorate_participation_payload(db, sid, payload)
    else:
        with _store(request).tx() as connection:
            result = decorate_participation_payload(connection, sid, payload)
    return web.json_response(result)


def decorate_export_snapshot(db, season_id, snapshot):
    """Status text only; export scope, columns, nulling and values stay intact."""
    return decorate_participation_payload(db, season_id, snapshot)
