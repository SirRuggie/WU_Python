from utils.cwl_roster_messages import clan_image_message, closing_message
from utils.dashboard_urls import ASSIGNMENTS_URL


def test_clan_message_is_short_and_preserves_full_file_attachment_transport():
    message = clan_image_message('W. U. Lazy.128', '#P2Y')
    assert message['content'] == '**W. U. Lazy.128**'
    assert message['allowed_mentions'] == {'parse': []}
    assert 'embeds' not in message
    assert message['attachments'] == []
    button = message['components'][0]['components'][0]
    assert button['label'] == 'Open clan' and button['url'].endswith('tag=%23P2Y')


def test_external_names_cannot_inject_formatting_mentions_or_lines():
    message = clan_image_message('**Bad**\n@everyone <@&123> [link](x)', '#P2Y')
    assert '\n' not in message['content']
    assert '@everyone' not in message['content']
    assert '\\*\\*Bad\\*\\*' in message['content']
    assert message['allowed_mentions'] == {'parse': []}


def test_test_payloads_match_production_except_explicit_no_ping_policy():
    for production, test in ((closing_message(), closing_message(test=True)),
                             (clan_image_message('Example', '#P2Y'), clan_image_message('Example', '#P2Y', test=True))):
        assert test['allowed_mentions'] == {'parse': [], 'roles': []}
        assert {k:v for k,v in test.items() if k != 'allowed_mentions'} == {
            k:v for k,v in production.items() if k != 'allowed_mentions'}
        assert 'TEST' not in str(test)
    assert closing_message()['content'] == "Can't find your name? Check My assignments."
    assert closing_message()['components'][0]['components'][0]['url'] == ASSIGNMENTS_URL
