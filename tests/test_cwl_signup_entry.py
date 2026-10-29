from copy import deepcopy

from utils import cwl_campaign
from cwl_web.app import login_destination


def test_near_limit_body_keeps_button_without_overflowing():
    import asyncio
    from tests.test_cwl_dashboard_integration import MemoryMongo
    async def run():
        for size in (3780, 3850):
            campaign = cwl_campaign.default_campaign()
            item = campaign['messages']['signup']['variants']['main']
            item.update(title='CWL signup information for this season', role_ids=[123456789012345678], body='x' * size)
            original = item['body']
            mongo = MemoryMongo()
            key = cwl_campaign.defaults_id(22)
            mongo.bot_config.documents[key] = {'_id': key, 'campaign': campaign}
            loaded = (await cwl_campaign.load_campaign(mongo, 22, '2030-10'))['campaign']
            saved = loaded['messages']['signup']['variants']['main']
            cwl_campaign.validate_campaign(loaded)
            assert saved['body'].startswith(original)
            assert saved['buttons'][1]['custom_id'] == cwl_campaign.SIGNUP_CHECK_ID
            if size == 3850:
                assert saved['body'] == original
    asyncio.run(run())


def test_signup_entry_upgrades_existing_templates_without_mutating_custom_content():
    campaign = cwl_campaign.default_campaign()
    campaign['messages']['signup']['variants']['main']['body'] = cwl_campaign.LEGACY_SIGNUP_MAIN
    campaign['messages']['reminder:1']['variants']['lazy']['body'] = 'Family-specific instructions'
    campaign['messages']['signup']['variants']['main']['buttons'] = [{'label': 'Old form', 'url': 'https://forms.gle/old'}]
    original = deepcopy(campaign)
    upgraded = cwl_campaign.normalize_signup_entry(campaign)
    assert campaign == original
    for key, message in upgraded['messages'].items():
        if key == 'signup' or key.startswith('reminder:'):
            for variant in message['variants'].values():
                assert variant['buttons'] == [{'label': 'Sign up for CWL', 'url': cwl_campaign.SIGNUP_URL}, {'label': 'Check my signups', 'custom_id': cwl_campaign.SIGNUP_CHECK_ID}]
    assert 'two signup forms' not in upgraded['messages']['signup']['variants']['main']['body']
    assert upgraded['messages']['reminder:1']['variants']['lazy']['body'] == 'Family-specific instructions\n\n' + cwl_campaign.SIGNUP_CHECK_LINE
    assert upgraded['messages']['roster'] == original['messages']['roster']
    assert upgraded['messages']['signup']['schedule'] == original['messages']['signup']['schedule']
    assert cwl_campaign.normalize_signup_entry(upgraded) == upgraded


def test_announcement_destination_is_supported_by_login():
    from urllib.parse import urlsplit, parse_qsl
    url = urlsplit(cwl_campaign.SIGNUP_URL)
    assert url.scheme == 'https'
    assert url.hostname == 'dash.warriorsunited.cc'
    assert url.path == '/signup'
    assert login_destination({'view': 'signup'}) == '/signup'


def test_saved_message_render_uses_direct_signup_link():
    import asyncio
    campaign = cwl_campaign.default_campaign()
    campaign['messages']['signup']['variants']['main']['buttons'] = [{'label': 'Old form', 'url': 'https://forms.gle/old'}]
    built = asyncio.run(cwl_campaign.render_message(campaign, 'signup', 'main', preview=False))[0].build()[0]
    assert cwl_campaign.SIGNUP_URL in str(built)
    assert 'forms.gle/old' not in str(built)


def test_saved_roster_links_upgrade_and_keep_guide_and_custom_copy():
    campaign = cwl_campaign.default_campaign()
    item = campaign['messages']['roster']['variants']['lazy']
    item['buttons'][0]['url'] = cwl_campaign.LEGACY_ROSTER_URLS[1]
    item['body'] = 'Custom instructions'
    guide = deepcopy(item['buttons'][1])
    result = cwl_campaign.normalize_signup_entry(campaign)
    saved = result['messages']['roster']['variants']['lazy']
    assert saved['buttons'][0]['url'] == 'https://dash.warriorsunited.cc/assignments'
    assert saved['buttons'][1] == guide
    assert saved['body'] == 'Custom instructions'
    assert item['buttons'][0]['url'] == cwl_campaign.LEGACY_ROSTER_URLS[1]


def test_signup_help_footer_covers_both_pools_and_all_reminders_only():
    import asyncio
    campaign = cwl_campaign.default_campaign()
    original = deepcopy(campaign)
    for key, message in campaign['messages'].items():
        for pool in message['variants']:
            built = asyncio.run(cwl_campaign.render_message(campaign, key, pool, preview=False))[0].build()[0]
            children = built['components']
            signup = key == 'signup' or key.startswith('reminder:')
            assert str(built).count(cwl_campaign.SIGNUP_HELP_LINE) == int(signup)
            if signup:
                assert children[-1]['content'] == cwl_campaign.SIGNUP_HELP_LINE
                assert children[-2]['type'] == 14
                assert children[-2]['divider'] is True
                assert children[-3]['type'] == 1
                assert len(children[-3]['components']) == 2
                assert children[-3]['components'][0]['url'] == cwl_campaign.SIGNUP_URL
                assert children[-3]['components'][1]['custom_id'] == cwl_campaign.SIGNUP_CHECK_ID
                assert str(built).count(cwl_campaign.SIGNUP_CHECK_LINE) == 1
            assert 'cwl signup' not in str(built)
    assert campaign == original
