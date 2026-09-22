import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands import content
from extensions.components import registered_functions


def _count_components(items):
    return sum(1 + _count_components(getattr(item, "components", ())) for item in items)


def test_native_document_baselines_keep_original_layout_and_text_totals():
    async def check():
        expected = {"about-us": (12, 2819), "strike-system": (12, 3585), "family-particulars": (28, 3992)}
        expected_components = {"about-us": 22, "strike-system": 29, "family-particulars": 40}
        for key, document in content.DOCUMENTS.items():
            components = await content.baseline(document)
            nodes = content.text_nodes(components)
            assert (len(nodes), sum(len(node.content) for node in nodes)) == expected[key]
            assert _count_components(components) == expected_components[key]
            preview = await content.render(document, [node.content for node in nodes], preview=True)
            assert sum(len(node.content) for node in content.text_nodes(preview)) == expected[key][1]
            assert _count_components(preview) == expected_components[key]
    asyncio.run(check())


def test_registry_baselines_use_the_public_pure_renderers(monkeypatch):
    from extensions.commands.setup import recruit_aboutus, recruit_familyparticulars, recruit_strikesystem

    calls = []
    originals = {
        "about-us": recruit_aboutus.build_aboutus,
        "strike-system": recruit_strikesystem.build_strikesystem,
        "family-particulars": recruit_familyparticulars.build_familyparticulars,
    }

    def tracked(key):
        def build(*args, **kwargs):
            calls.append((key, args, kwargs))
            return originals[key](*args, **kwargs)
        return build

    monkeypatch.setattr(recruit_aboutus, "build_aboutus", tracked("about-us"))
    monkeypatch.setattr(recruit_strikesystem, "build_strikesystem", tracked("strike-system"))
    monkeypatch.setattr(recruit_familyparticulars, "build_familyparticulars", tracked("family-particulars"))
    monkeypatch.setattr(content, "_baselines", {})

    async def check():
        for document in content.DOCUMENTS.values():
            await content.baseline(document)

    asyncio.run(check())
    assert calls == [("about-us", (), {}), ("strike-system", (), {}), ("family-particulars", (), {})]


def test_pure_setup_renderers_accept_sections_without_changing_the_component_shape():
    from extensions.commands.setup import recruit_familyparticulars, recruit_strikesystem

    for build in (recruit_strikesystem.build_strikesystem, recruit_familyparticulars.build_familyparticulars):
        original = build()
        sections = [node.content for node in content.text_nodes(original)]
        sections[0] += " (edited)"
        rendered = build(sections, action_id="draft", preview=True)
        assert content.component_shape(rendered) == content.component_shape(original)
        assert _count_components(rendered) == _count_components(original)
        assert content.text_nodes(rendered)[0].content == sections[0]


def test_family_decorations_remain_fixed_and_named_blocks_are_semantic():
    async def check():
        document = content.DOCUMENTS["family-particulars"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
        blocks = content.editable_blocks(document, sections)
        assert len(blocks) == 20
        assert all("ᨖ" not in sections[index] for index, _label in blocks)
        assert blocks[0][1] == "Family heading"
        assert blocks[-1][1] == "Acknowledgement"
    asyncio.run(check())


def test_render_rejects_a_full_document_over_discord_limit():
    async def check():
        document = content.DOCUMENTS["family-particulars"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
        sections[0] += "over limit"
        with pytest.raises(ValueError, match="4,000"):
            await content.render(document, sections)
    asyncio.run(check())


def test_content_actions_use_modal_and_state_contracts():
    expected = {
        "content_document": (False, False, False), "content_block": (True, False, True),
        "content_submit": (False, True, True), "content_preview": (False, False, False),
        "content_save": (False, False, False), "content_publish": (False, False, False),
        "content_back_root": (False, False, False), "content_back_document": (False, False, False),
    }
    for name, (*flags, no_return) in expected.items():
        action = registered_functions[name]
        assert (action.opens_modal, action.is_modal) == tuple(flags)
        assert action.no_return is no_return and action.preload_state is False


def test_dashboard_command_description_matches_the_published_server_scope():
    assert content.ContentDashboard._command_data.description == "Edit published server content"


def test_image_upload_declares_required_options_before_its_optional_slot():
    options = content.ContentImageUpload._command_data.options
    assert list(options) == ["draft", "image", "slot"]
    assert options["slot"].default is None


def test_every_dashboard_interaction_rechecks_permission_and_owner():
    class Ctx:
        user = SimpleNamespace(id=1)
        interaction = SimpleNamespace(guild_id=2, member=SimpleNamespace(permissions=hikari.Permissions.NONE))
        respond = AsyncMock()
    assert asyncio.run(content.require_editor(Ctx())) is False
    assert Ctx.respond.await_args.kwargs["ephemeral"] is True


def test_model_like_fetched_text_components_are_read_for_stale_checks():
    node = SimpleNamespace(type=hikari.ComponentType.TEXT_DISPLAY, content="from Discord")
    container = SimpleNamespace(components=(node,))
    assert content.text_nodes((container,)) == [node]


def test_family_schema_does_not_change_when_editable_copy_contains_decorative_glyph():
    async def check():
        document = content.DOCUMENTS["family-particulars"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
        sections[0] += " ᨖ"
        assert len(content.editable_blocks(document, sections)) == 20
    asyncio.run(check())


def test_missing_clan_record_returns_before_constructing_clan():
    from extensions.commands.clan.dashboard import update_clan_info_general
    ctx = SimpleNamespace(respond=AsyncMock(), interaction=SimpleNamespace())
    mongo = SimpleNamespace(clans=SimpleNamespace(find_one=AsyncMock(return_value=None)))
    assert asyncio.run(update_clan_info_general.update_general_info_panel(ctx, "#MISSING", mongo=mongo)) is None
    assert ctx.respond.await_args.kwargs["ephemeral"] is True


def test_revoked_clan_dashboard_role_is_refused_before_child_mutation():
    from extensions.commands.clan.dashboard.permissions import require_dashboard_role
    ctx = SimpleNamespace(
        interaction=SimpleNamespace(member=SimpleNamespace(get_roles=lambda: ())),
        respond=AsyncMock(),
    )
    assert asyncio.run(require_dashboard_role(ctx, 993015846442127420, "Clan Management")) is False
    assert ctx.respond.await_args.kwargs["ephemeral"] is True
