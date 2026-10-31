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


def test_closing_and_test_copies_never_ping():
    for message in (closing_message(), closing_message(test=True), clan_image_message('Example', '#P2Y', test=True)):
        assert message['allowed_mentions'] == {'parse': []}
    closing = closing_message()
    assert closing['content'] == "Can't find your name? Check My assignments."
    assert closing['components'][0]['components'][0]['url'] == ASSIGNMENTS_URL
    assert closing_message(test=True)['content'].startswith('TEST · ')
