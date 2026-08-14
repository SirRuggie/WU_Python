import asyncio
import warnings

from utils import startup


def test_extension_discovery_only_returns_loader_entry_points():
    discovered = startup.load_cogs(
        disallowed={"example"}, disallowed_folders={"tickets"}
    )

    assert "extensions.commands.accounts" in discovered
    assert "extensions.commands.cards" in discovered
    assert "extensions.commands.poll" in discovered
    assert "extensions.commands.todo" in discovered
    assert "extensions.commands.fwa.lazy_cwl" in discovered
    assert "extensions.commands.clan.dashboard.dashboard" in discovered
    assert "extensions.commands.help_catalog" not in discovered
    assert "extensions.commands.fwa.helpers" not in discovered
    assert "extensions.commands.clan.info_hub.helpers" not in discovered
    assert "extensions.commands.recruit.dashboard.manage_roles" not in discovered


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
    assert "extensions.commands.cards" in extensions
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
