import hikari

from extensions.commands.fwa.bases import Bases
from extensions.commands.fwa.new_th_upgrade import NewThUpgrade


def test_user_pickers_keep_identity_and_exact_approved_description():
    for command in (Bases, NewThUpgrade):
        option = command._command_data.options['discord-user']
        assert option.description == 'User to show this to'
        assert option.name == 'discord-user'
        assert option.type is hikari.OptionType.USER
