"""Defaults materialization may share a cycle revision with a field-only save."""
import asyncio
from copy import deepcopy

import pytest
from test_cwl_campaign_catchup import runtime, GUILD, CYCLE
from extensions.tasks import cwl_reminder as native
from utils import cwl_campaign as campaign, cwl_web_bridge as bridge

FUTURE = '2026-12'
CANDIDATE = {
    'title': 'Reviewed roster only',
    'body': 'Synthetic confirmed pool text',
    'buttons': [{'label': 'My tasks', 'url': 'https://dash.warriorsunited.cc/tasks'}],
}


@pytest.mark.parametrize('window', ['before-metadata-read', 'after-metadata-read'])
@pytest.mark.parametrize('future_months', [False, True])
@pytest.mark.parametrize('marked', [False, True])
@pytest.mark.parametrize('row_shape', ['receipt-only', 'missing'])
def test_defaults_materialization_interleave_preserves_current_and_future_copy(
    runtime, monkeypatch, window, future_months, marked, row_shape,
):
    async def run():
        mongo = runtime.mongo
        # Model the separate dashboard process, not a same-process bot scheduler.
        monkeypatch.setattr(native, 'bot_instance', None)
        monkeypatch.setattr(native, 'mongo_client', None)
        defaults = mongo.bot_config.documents[campaign.defaults_id(GUILD)]
        if not marked:
            defaults['campaign'].pop(campaign.DEFAULT_COPY_FIELD, None)
        key = campaign.cycle_id(GUILD, CYCLE)
        if row_shape == 'receipt-only':
            mongo.bot_config.documents[key] = {
                '_id': key, 'kind': 'cwl_campaign_cycle', 'guild_id': GUILD,
                'cycle': CYCLE, 'revision': 0, 'activated': True,
                'deliveries': [{'occurrence_id': CYCLE + '|roster|main', 'status': 'sent', 'message_id': 9001}],
                'sent_occurrences': [CYCLE + '|roster|main'],
            }
        before = await campaign.load_campaign(mongo, GUILD, CYCLE)
        draft = await campaign.new_draft(mongo, GUILD, 200, cycle=CYCLE, scope='defaults')
        new_defaults = deepcopy(draft['campaign'])
        new_defaults['messages']['signup']['variants']['main']['title'] = 'New future signup default'
        new_defaults['messages']['roster']['variants']['main']['body'] = 'New future roster default'
        await campaign.patch_draft(mongo, draft['token'], {'campaign': new_defaults})
        serial_initial = deepcopy(mongo.bot_config.documents)
        initial_clock = runtime.clock[0]
        force_before = False
        original_find = mongo.bot_config.find_one
        original_update = mongo.bot_config.update_one
        reads = 0
        injected = False
        observation = {}

        async def defaults_save():
            nonlocal injected
            injected = True
            runtime.clock[0] = runtime.clock[0].add(seconds=1)
            await campaign.apply_draft(mongo, draft['token'], 200)
            materialized = mongo.bot_config.documents[key]
            current = await campaign.load_campaign(mongo, GUILD, CYCLE)
            future = await campaign.load_campaign(mongo, GUILD, FUTURE)
            observation.update(
                materialized_revision=materialized['revision'],
                materialized_campaign_present=isinstance(materialized.get('campaign'), dict),
                current_after_defaults=deepcopy(current['campaign']),
                future_after_defaults=deepcopy(future['campaign']),
            )

        async def read(query):
            nonlocal reads
            if query.get('_id') == key and not injected:
                reads += 1
                # First read belongs to load_campaign; second is the separate
                # metadata read in save_updated_roster_variant.
                if (force_before or window == 'before-metadata-read') and reads == 2:
                    await defaults_save()
            return await original_find(query)

        async def update(query, changes, **kwargs):
            if (
                not injected and not force_before and window == 'after-metadata-read'
                and query.get('_id') == key
                and 'roster_copy_edit_revision' in changes.get('$set', {})
            ):
                await defaults_save()
            return await original_update(query, changes, **kwargs)

        monkeypatch.setattr(mongo.bot_config, 'find_one', read)
        monkeypatch.setattr(mongo.bot_config, 'update_one', update)
        await campaign.save_updated_roster_variant(
            mongo, guild_id=GUILD, cycle=CYCLE, pool='main', user_id=200,
            candidate=CANDIDATE, expected_generation=bridge.campaign_generation(before),
            future_months=future_months,
        )
        assert injected
        assert observation['materialized_revision'] == before['revision'] == 0
        assert observation['materialized_campaign_present']
        assert observation['current_after_defaults'] == before['campaign']
        current = await campaign.load_campaign(mongo, GUILD, CYCLE)
        future = await campaign.load_campaign(mongo, GUILD, FUTURE)
        expected_current = deepcopy(before['campaign'])
        expected_current['messages']['roster']['variants']['main'].update(CANDIDATE)
        expected_future = deepcopy(observation['future_after_defaults'])
        if future_months:
            expected_future['messages']['roster']['variants']['main'].update(CANDIDATE)
        assert current['campaign'] == expected_current
        assert future['campaign'] == expected_future
        assert current['deliveries'] == before['deliveries']
        assert current['sent_occurrences'] == before['sent_occurrences']
        assert current['defaults_revision'] == 2 and current['revision'] == 1
        row = mongo.bot_config.documents[key]
        written_missing = row['roster_copy_base_campaign_missing']
        async def followups():
            runtime.clock[0] = runtime.clock[0].add(seconds=2)
            later = await campaign.new_draft(mongo, GUILD, 200, cycle=CYCLE, scope='defaults')
            later_copy = deepcopy(later['campaign'])
            later_copy['messages']['signup']['variants']['main']['title'] = 'Second future-only signup'
            later_copy['messages']['roster']['variants']['main']['title'] = 'Second future-only roster'
            await campaign.patch_draft(mongo, later['token'], {'campaign': later_copy})
            await campaign.apply_draft(mongo, later['token'], 200)
            after_later = await campaign.load_campaign(mongo, GUILD, CYCLE)
            assert after_later['campaign'] == expected_current
            future_after_later = await campaign.load_campaign(mongo, GUILD, FUTURE)
            runtime.clock[0] = runtime.clock[0].add(seconds=2)
            opposite = {**CANDIDATE, 'title': 'Reviewed opposite pool', 'body': 'Lazy-only confirmed copy'}
            await campaign.save_updated_roster_variant(
                mongo, guild_id=GUILD, cycle=CYCLE, pool='lazy', user_id=200,
                candidate=opposite, expected_generation=bridge.campaign_generation(after_later),
                future_months=future_months,
            )
            final_expected = deepcopy(expected_current)
            final_expected['messages']['roster']['variants']['lazy'].update(opposite)
            final_current = await campaign.load_campaign(mongo, GUILD, CYCLE)
            final_future = await campaign.load_campaign(mongo, GUILD, FUTURE)
            assert final_current['campaign'] == final_expected
            for observed in (after_later, final_current):
                assert observed['deliveries'] == before['deliveries']
                assert observed['sent_occurrences'] == before['sent_occurrences']
            assert final_current['revision'] == 2 and final_current['defaults_revision'] == 3
            return deepcopy((after_later, future_after_later, final_current, final_future))
        raced_followups = await followups()
        # Replay the exact saves with defaults materialized before the metadata
        # read. This is an operation-order reference, not a guessed draft ==
        # effective-copy assumption (177 normalizes copy and recurring overlays).
        mongo.bot_config.documents = deepcopy(serial_initial)
        runtime.clock[0] = initial_clock
        injected = False
        reads = 0
        force_before = True
        await campaign.save_updated_roster_variant(
            mongo, guild_id=GUILD, cycle=CYCLE, pool='main', user_id=200,
            candidate=CANDIDATE, expected_generation=bridge.campaign_generation(before),
            future_months=future_months,
        )
        serial_followups = await followups()
        for raced, serial in zip(raced_followups, serial_followups):
            assert raced['campaign'] == serial['campaign']
            assert raced['deliveries'] == serial['deliveries']
            assert raced['sent_occurrences'] == serial['sent_occurrences']
        assert not runtime.rest.sent
    asyncio.run(run())
