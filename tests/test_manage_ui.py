"""Navigation icons preserve visible labels and distinct action meanings."""
import hikari

from utils.manage_ui import button_emoji, breadcrumb


def test_navigation_buttons_serialize_custom_icons_without_changing_labels():
    expected = {
        'Back to FWA': 1536796427198668911,
        'Management Home': 1536924506147524730,
        'Previous': 1536793616863862784,
        'Next': 1536793616004022403,
        'Refresh': 1536798918858514502,
        'Search members': 1536797595089899540,
        'Advanced settings': 1537238367857676310,
        'Edit message': 1537264251603779764,
        'Confirm': 1397096942907166831,
        'Cancel': 1397096986506825778,
    }
    for label, emoji_id in expected.items():
        button = hikari.impl.InteractiveButtonBuilder(
            style=hikari.ButtonStyle.SECONDARY, custom_id='test',
            label=label, emoji=button_emoji(label),
        ).build()[0]
        assert button['label'] == label
        assert int(button['emoji']['id']) == emoji_id
    assert button_emoji('Next step') is hikari.UNDEFINED
    assert button_emoji('Open') is hikari.UNDEFINED
    assert button_emoji('Send reminder now') is hikari.UNDEFINED
    assert breadcrumb('FWA', 'Points Monitor') == '-# Management › FWA › Points Monitor'
