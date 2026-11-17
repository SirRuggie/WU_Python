"""Ordinary fixture proof that strike maintenance never owns activity TTLs."""

from copy import deepcopy
import json

import pytest

from tests.test_player_activity import NOW
from tests.test_strike_retention_migration import Client, populated
from tools.maintenance.strike_retention import migrate
from utils.strike_retention import validate_record_retention


@pytest.mark.parametrize('apply', [False, True])
def test_strike_maintenance_never_accesses_activity_and_preserves_strike_policy(tmp_path, apply):
    client, routes = populated()
    database = client['fixture']
    activity = database['player_activity']
    activity.rows = [
        {'_id': '#PYY', 'tag': '#PYY', 'left_at': NOW},
        {'_id': 'history-clan:#PQQ', 'kind': 'history_clan', 'left_at': NOW},
    ]
    activity.indexes = [('left_at', {'name': 'fixture_existing_index', 'expireAfterSeconds': 123})]
    before_activity = deepcopy((activity.rows, activity.indexes))
    before_profiles = deepcopy(database['strike_profiles'].rows)
    before_records = deepcopy(database['strike_records'].rows)
    before_snapshots = deepcopy(database['strike_war_snapshots'].rows)
    # A missing route makes any new access through the maintenance source fail.
    del routes['player_activity']
    result = migrate(client, routes, tmp_path/'backup', restore_client=Client(restore=True), apply=apply)
    assert result['restored'] is True
    assert result['ttl_applied'] is apply
    assert result['indexes'] == {
        'strike_records': 'applied' if apply else 'not_applied',
        'strike_war_snapshots': 'applied' if apply else 'not_applied',
    }
    assert json.loads((tmp_path/'backup/manifest.json').read_text())['indexes'] == result['indexes']
    assert (activity.rows, activity.indexes) == before_activity
    assert database['strike_profiles'].rows == before_profiles
    if apply:
        assert database['strike_records'].rows == [
            {**row, 'purge_after': validate_record_retention(row)} for row in before_records
        ]
        assert database['strike_war_snapshots'].rows == [
            {key: value for key, value in row.items() if key != 'purge_after'}
            for row in before_snapshots
        ]
        for name in ('strike_records', 'strike_war_snapshots'):
            assert database[name].indexes == [
                ('purge_after', {'expireAfterSeconds': 0, 'name': 'retention_purge_after'})
            ]
    else:
        assert database['strike_records'].rows == before_records
        assert database['strike_war_snapshots'].rows == before_snapshots
        assert database['strike_records'].indexes == []
        assert database['strike_war_snapshots'].indexes == []
