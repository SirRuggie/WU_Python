import asyncio
from types import SimpleNamespace

from extensions.commands import family_links


def test_family_role_menu_preserves_roles_and_uses_approved_descriptions():
    guild = SimpleNamespace(make_icon_url=lambda: None)
    panel = asyncio.run(family_links.build_family_links_panel(guild, object(), 'test', object()))[0]
    menu = next(row.components[0] for row in panel.components
                if hasattr(row, 'components') and len(row.components) == 1
                and getattr(row.components[0], 'custom_id', '') == 'family_links_server_roles:test')
    options = {option.label: option for option in menu.options}
    assert options['LazyCWL Participant'].description == 'Get this role to see the LazyCWL signups channel.'
    assert options['LazyCWL Participant'].value == 'server_role:772313841090297886'
    assert options['VC Participant'].description == 'A ping for members who want to talk.'
    assert options['VC Participant'].value == 'server_role:1148955348598788166'
    assert menu.min_values == 0 and menu.max_values == len(family_links.SERVER_ROLES)
