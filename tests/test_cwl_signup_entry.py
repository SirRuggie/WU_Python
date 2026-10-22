from copy import deepcopy

from utils import cwl_campaign
from cwl_web.app import login_destination


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
                assert variant['buttons'] == [{'label': 'Sign up for CWL', 'url': cwl_campaign.SIGNUP_URL}]
    assert 'two signup forms' not in upgraded['messages']['signup']['variants']['main']['body']
    assert upgraded['messages']['reminder:1']['variants']['lazy']['body'] == 'Family-specific instructions'
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
