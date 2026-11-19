"""Registry-driven weight math and inert Discord dashboard cards."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hikari
import pytest
from utils import town_halls as store
from extensions.commands.fwa import weight
from extensions.commands import fwa_weight_dashboard as ui
from town_halls_fixture import weight_registry


def run(coro): return asyncio.run(coro)


def text_of(components):
    def walk(value):
        if isinstance(value, dict):
            yield value.get('content','')
            for item in value.get('components',[]):yield from walk(item)
        elif isinstance(value, list):
            for item in value:yield from walk(item)
    return '\n'.join(walk([item.build()[0] for item in components]))


def test_fwa_minimum_filters_calculation_and_guide_without_mutating_legacy_ranges():
    config=weight_registry()
    assert store.weight_ranges(config)[12]['min']==111000
    assert 11 not in store.weight_ranges(config)
    assert config['levels']['11']['weight']['min']==91000
    text=weight.format_weight_reference_guide(120000,12,config)
    assert '(TH12)' in text and '(TH18)' in text and '(TH11)' not in text
    assert weight.determine_town_hall(110000,store.weight_ranges(config))[:2]==(None,'below')


@pytest.mark.parametrize('level',range(12,20))
@pytest.mark.parametrize('position',[0,25,50,100])
def test_position_math_matches_previous_formula_for_fwa_levels(level,position):
    ranges=store.weight_ranges(weight_registry(newest=19))
    low,high=ranges[level]['min'],ranges[level]['max']
    total=low+(high-low)*position//100
    assert weight.calculate_position_in_range(total,level,ranges)==int((total-low)/(high-low)*100)
    assert weight.determine_town_hall(total,ranges)[:2]==(level,'exact')


def test_new_th_bounds_gap_and_upgrade():
    config=weight_registry(newest=19);ranges=store.weight_ranges(config)
    assert weight.determine_town_hall(190000,ranges)[:2]==(19,'exact')
    assert weight.determine_town_hall(190001,ranges)[1]=='above'
    assert weight.determine_town_hall(180500,ranges)[:2]==(18,'between')
    assert 'TH19' in weight.get_upgrade_info(180000,18,ranges)
    assert '(TH19)' in weight.format_weight_reference_guide(185000,19,config)


def test_saved_markup_only_no_name_lookup_or_map_fallback(monkeypatch):
    config=weight_registry(newest=19)
    config['levels']['19']['emoji']='<:TH_19A:1571025137896005783>'
    assert weight.get_th_emoji(19,config)==config['levels']['19']['emoji']
    assert weight.get_th_emoji(18,config)==''
    monkeypatch.setattr(store,'_snapshot',None)
    assert weight.get_th_emoji(19)==''
    assert weight.determine_town_hall(190000)[:2]==(None,'unknown')
    assert weight.format_weight_reference_guide(190000,19)==''


@pytest.mark.parametrize('admin',[False,True])
def test_legacy_controls_are_private_dashboard_links_without_data_access(admin):
    ctx=SimpleNamespace(interaction=SimpleNamespace(member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR if admin else hikari.Permissions.NONE)),respond=AsyncMock())
    for action in (ui.refresh,ui.save):
        run(action(ctx,'expired-token'))
        kwargs=ctx.respond.call_args.kwargs
        assert kwargs['ephemeral'] is True
        if admin:
            payload=[item.build()[0] for item in kwargs['components']]
            assert 'Town Halls are managed on the dashboard.' in str(payload)
            assert 'https://dash.warriorsunited.cc/manage/town-halls' in str(payload)
            assert 'custom_id' not in str(payload)
        else:assert ctx.respond.call_args.args==('You need Administrator permission.',)


def test_card_uses_no_database_and_open_dashboard_keeps_existing_private_response():
    ctx=SimpleNamespace(interaction=SimpleNamespace(member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR),edit_initial_response=AsyncMock()),defer=AsyncMock())
    run(ui.open_dashboard(ctx,object(),manage_token='unused'))
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    assert 'Town Halls' in text_of(ctx.interaction.edit_initial_response.call_args.kwargs['components'])


def test_calculator_uses_registry_settings_without_discord_emoji_fetch(monkeypatch):
    config=weight_registry(newest=19);config['lowest_fwa_town_hall']=13
    monkeypatch.setattr(store,'load',AsyncMock(return_value=config))
    ctx=SimpleNamespace(guild_id=2,channel_id=3,defer=AsyncMock(),interaction=SimpleNamespace(delete_initial_response=AsyncMock()))
    bot=SimpleNamespace(rest=SimpleNamespace(create_message=AsyncMock(),fetch_application_emojis=AsyncMock()))
    run(weight.WeightCommand.invoke(SimpleNamespace(weight=38000,user=None),ctx,bot,object()))
    text=text_of(bot.rest.create_message.call_args.kwargs['components'])
    assert 'Town Hall 19' in text and 'TH13–TH19' in text and '(TH12)' not in text
    bot.rest.fetch_application_emojis.assert_not_awaited()
