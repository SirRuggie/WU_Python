import asyncio
import warnings
from pathlib import Path

from utils import startup


def test_extension_discovery_only_returns_loader_entry_points():
    discovered = startup.load_cogs(
        disallowed={"example"}, disallowed_folders={"tickets"}
    )

    assert "extensions.commands.accounts" in discovered
    assert "extensions.commands.cards" not in discovered
    assert "extensions.commands.ping" in discovered
    assert "extensions.commands.poll" in discovered
    assert "extensions.commands.todo" in discovered
    assert "extensions.commands.fwa.lazy_cwl" in discovered
    assert "extensions.commands.clan.dashboard.dashboard" in discovered
    assert "extensions.commands.help_catalog" not in discovered
    assert "extensions.commands.fwa.helpers" not in discovered
    assert "extensions.commands.clan.info_hub.helpers" not in discovered
    assert "extensions.commands.recruit.dashboard.manage_roles" not in discovered


def test_development_preview_extensions_are_retained_but_not_discovered():
    discovered = set(startup.load_cogs(
        disallowed={"example"}, disallowed_folders={"tickets"}
    ))
    preview_modules = {
        "cards_bulk_preview": "extensions.commands.cards_bulk_preview",
        "cards_preview": "extensions.commands.cards_preview",
        "poll_bar_preview": "extensions.commands.poll_bar_preview",
    }

    assert startup.DISABLED_PREVIEW_EXTENSIONS == frozenset(preview_modules)
    for module_stem, module_name in preview_modules.items():
        source = startup.COMMANDS_ROOT / f"{module_stem}.py"
        assert source.is_file()
        assert startup._binds_loader(source)
        assert module_name not in discovered


def test_explicit_and_discovered_extensions_are_loaded_once():
    assert startup.unique_extensions(
        ["extensions.one", "extensions.two"],
        ["extensions.two", "extensions.three", "extensions.one"],
    ) == ["extensions.one", "extensions.two", "extensions.three"]


def test_shared_loader_command_families_use_one_package_entry_point():
    packages = [
        "extensions.commands.clan",
        "extensions.commands.fwa",
        "extensions.commands.recruit",
        "extensions.commands.recruit.dashboard.server_walkthrough",
        "extensions.commands.setup",
        "extensions.commands.tickets",
    ]
    discovered = startup.load_cogs(
        disallowed={"example"},
        disallowed_folders={"clan", "fwa", "recruit", "setup", "tickets"},
    )
    extensions = startup.unique_extensions(packages, discovered)

    assert len(extensions) == len(set(extensions))
    assert "extensions.commands.fwa" in extensions
    assert "extensions.commands.fwa.lazy_cwl" not in extensions
    assert "extensions.commands.clan.list" not in extensions
    assert "extensions.commands.recruit.questions" not in extensions
    assert "extensions.commands.setup.recruit_aboutus" not in extensions
    assert "extensions.commands.accounts" in extensions
    assert "extensions.commands.cards" not in extensions
    assert "extensions.commands.todo" in extensions


def test_clash_client_is_created_on_running_loop_without_deprecation_warning():
    async def create():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client = startup.create_clash_client()
        return client, caught, asyncio.get_running_loop()

    client, caught, loop = asyncio.run(create())

    assert client.loop is loop
    assert not any("There is no current event loop" in str(item.message) for item in caught)


def test_tickets_guild_id_reads_the_environment_on_every_call(monkeypatch):
    monkeypatch.delenv("TICKETS_GUILD_ID", raising=False)
    assert startup.tickets_guild_id() == startup.TICKETS_GUILD_ID_DEFAULT

    monkeypatch.setenv("TICKETS_GUILD_ID", "123456789")
    assert startup.tickets_guild_id() == 123456789

    monkeypatch.delenv("TICKETS_GUILD_ID", raising=False)
    assert startup.tickets_guild_id() == startup.TICKETS_GUILD_ID_DEFAULT


def test_tickets_guild_id_falls_back_on_a_bad_value(monkeypatch, capsys):
    monkeypatch.setenv("TICKETS_GUILD_ID", "not-a-number")
    assert startup.tickets_guild_id() == startup.TICKETS_GUILD_ID_DEFAULT
    assert "TICKETS_GUILD_ID" in capsys.readouterr().out

    monkeypatch.setenv("TICKETS_GUILD_ID", "0")
    assert startup.tickets_guild_id() == startup.TICKETS_GUILD_ID_DEFAULT

    monkeypatch.setenv("TICKETS_GUILD_ID", "-5")
    assert startup.tickets_guild_id() == startup.TICKETS_GUILD_ID_DEFAULT


def test_retired_extensions_are_kept_but_not_loaded():
    retired_command_sources = {
        "extensions.commands.cards": "extensions/commands/cards.py",
        "extensions.tasks.cards_sticky": "extensions/tasks/cards_sticky.py",
        "extensions.tasks.cards_deadlines": "extensions/tasks/cards_deadlines.py",
    }

    assert startup.RETIRED_EXTENSIONS == frozenset(retired_command_sources)
    for module_name, relative_path in retired_command_sources.items():
        assert Path(relative_path).is_file(), module_name

    extensions = ["extensions.one", *retired_command_sources, "extensions.two"]
    assert startup.active_extensions(extensions) == ["extensions.one", "extensions.two"]

    discovered = startup.load_cogs(
        disallowed={"example"}, disallowed_folders={"tickets"}
    )
    assert "extensions.commands.cards" not in discovered
