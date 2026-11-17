"""Fixture-only D19 index contract; no Mongo connection or TTL scheduler."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.test_player_activity import NOW
from tests.test_player_activity_store import ActivityCollection, CLAN, PLAYER
from utils.player_activity_store import PlayerActivityStore


class IndexCollection(ActivityCollection):
    def __init__(self):
        super().__init__()
        self.index_calls = []

    async def create_index(self, key, **options):
        self.index_calls.append((key, options))


def matches_partial(row, predicate):
    """Model the supported predicate for scalar fixtures (not a Mongo emulator)."""
    for field, condition in predicate.items():
        value = row.get(field)
        if not isinstance(condition, dict):
            if value != condition:
                return False
            continue
        for operator, operand in condition.items():
            if operator == '$exists':
                assert operand is True
                if field not in row:
                    return False
            elif operator == '$type':
                if operand == 'string':
                    if not isinstance(value, str):
                        return False
                elif operand == 'date':
                    if not isinstance(value, type(NOW)):
                        return False
                else:
                    raise AssertionError(f'Unexpected BSON type: {operand}')
            else:
                raise AssertionError(f'Unsupported partial operator: {operator}')
    return True


def test_index_definition_preserves_existing_index_without_document_writes():
    async def run():
        collection = IndexCollection()
        collection.rows[PLAYER] = {'_id': PLAYER, 'tag': PLAYER, 'left_at': NOW}
        before = deepcopy(collection.rows)
        store = PlayerActivityStore(SimpleNamespace(player_activity=collection))
        await store.ensure_indexes()
        assert collection.index_calls == [
            ('current_clan_tag', {'name': 'activity_family_clan'}),
            ('left_at', {
                'name': 'activity_departed_player_180d',
                'expireAfterSeconds': 15_552_000,
                'partialFilterExpression': {
                    'kind': None,
                    'tag': {'$type': 'string'},
                    'left_at': {'$exists': True, '$type': 'date'},
                },
            }),
        ]
        assert collection.rows == before
    asyncio.run(run())


@pytest.mark.parametrize('left_at', [None, '2026-01-01', 0, True, {}])
def test_scalar_non_dates_are_excluded(left_at):
    async def run():
        collection = IndexCollection()
        await PlayerActivityStore(SimpleNamespace(player_activity=collection)).ensure_indexes()
        predicate = collection.index_calls[1][1]['partialFilterExpression']
        assert not matches_partial({'tag': PLAYER, 'left_at': left_at}, predicate)
        assert not matches_partial({'tag': PLAYER}, predicate)
        assert not matches_partial({'left_at': NOW}, predicate)
        assert not matches_partial({'tag': 1, 'left_at': NOW}, predicate)
    asyncio.run(run())


def test_real_store_shapes_exclude_retired_history_and_returning_players():
    async def run():
        collection = IndexCollection()
        store = PlayerActivityStore(SimpleNamespace(player_activity=collection))
        await store.record({'tag': PLAYER, 'attackWins': 1}, CLAN, now=NOW)
        await store.save_history_clan(CLAN, {'wars': []}, now=NOW)
        await store.retire_history_clans(set(), now=NOW)
        await store.reconcile_membership({}, now=NOW)
        before = deepcopy(collection.rows)
        await store.ensure_indexes()
        predicate = collection.index_calls[1][1]['partialFilterExpression']
        assert collection.rows == before
        eligible = [row['_id'] for row in collection.rows.values()
                    if matches_partial(row, predicate)]
        assert eligible == [PLAYER]
        history = (await store.history_clans())[0]
        assert history['left_at'] == NOW
        assert not matches_partial({**history, 'tag': PLAYER}, predicate)
        assert not matches_partial({**history, '_id': PLAYER, 'tag': PLAYER}, predicate)
        assert matches_partial({**before[PLAYER], 'kind': None}, predicate)
        assert not matches_partial({**before[PLAYER], 'kind': 'other'}, predicate)
        # Eligibility begins immediately, but expiry is based on left_at + 180d.
        assert before[PLAYER]['left_at'] + timedelta(days=180) == NOW + timedelta(days=180)
        await store.reconcile_membership({PLAYER: CLAN}, now=NOW + timedelta(days=1))
        assert not matches_partial(await store.get(PLAYER), predicate)
        assert len(collection.rows) == 2
        assert (await store.history_clans())[0] == history
    asyncio.run(run())
