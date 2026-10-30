"""Pure reviewed correction plan. All persistence remains owned by StrikeService."""
from hashlib import sha256
from bson import json_util

WAR_KEYS = (
    '#8CV0GPPR:#2CYVV92R:2026-10-30T07:20:46+00:00',
    '#9UGQ0GL:#2CYVV92R:2026-09-22T07:41:24+00:00',
)
CORRECTION = 'no-attack-2026-10-30'
REASON = 'No-attack war (NO WAR)'
ACTOR = 'Ruggie (approved 2026-10-30)'


def digest(rows):
    return sha256(json_util.dumps(sorted(rows, key=lambda row: row['_id']),
                                  sort_keys=True).encode()).hexdigest()


def correction_plan(rows, profiles):
    targets = [row for row in rows if row.get('war_key') in WAR_KEYS]
    unrelated = [row for row in rows if row.get('war_key') not in WAR_KEYS]
    changed_streaks = sorted({row['player_tag'] for row in targets
                             if row.get('streak_eligible') or row.get('streak_receipt')})
    changed_streaks = sorted(set(changed_streaks) | {
        row['player_tag'] for row in profiles
        if row.get('streak_last_war_key') in WAR_KEYS
        or (row.get('streak_pending') or {}).get('war_key') in WAR_KEYS})
    changes = [row for row in targets if
               (row.get('kind') == 'strike' and not row.get('revoked_at'))
               or row.get('kind') == 'missed']
    return {'fingerprint': digest(targets), 'unrelated_hash': digest(unrelated),
            'records': targets, 'changes': [row['_id'] for row in changes],
            'strike_count': sum(row.get('kind') == 'strike' for row in changes),
            'neutral_count': sum(row.get('kind') == 'missed' for row in changes),
            'streak_review_accounts': changed_streaks}
