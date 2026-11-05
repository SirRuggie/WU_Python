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
        expected = {"about-us": (12, 2579), "strike-system": (12, 3236), "family-particulars": (28, 3710)}
        expected_components = {"about-us": 22, "strike-system": 29, "family-particulars": 40}
        for key in expected:
            document = content.DOCUMENTS[key]
            components = await content.baseline(document)
            nodes = content.text_nodes(components)
            assert (len(nodes), sum(len(node.content) for node in nodes)) == expected[key]
            assert _count_components(components) == expected_components[key]
            preview = await content.render(document, [node.content for node in nodes], preview=True)
            assert sum(len(node.content) for node in content.text_nodes(preview)) == expected[key][1]
            assert _count_components(preview) == expected_components[key]
    asyncio.run(check())


def test_registry_baselines_use_the_public_pure_renderers(monkeypatch):
    from extensions.commands.setup import recruit_aboutus, recruit_familyparticulars, recruit_strikesystem, recruit_join_family

    calls = []
    originals = {
        "join-family": recruit_join_family.build_join_family,
        "about-us": recruit_aboutus.build_aboutus,
        "strike-system": recruit_strikesystem.build_strikesystem,
        "family-particulars": recruit_familyparticulars.build_familyparticulars,
    }

    def tracked(key):
        def build(*args, **kwargs):
            calls.append((key, args, kwargs))
            return originals[key](*args, **kwargs)
        return build

    monkeypatch.setattr(recruit_join_family, "build_join_family", tracked("join-family"))
    monkeypatch.setattr(recruit_aboutus, "build_aboutus", tracked("about-us"))
    monkeypatch.setattr(recruit_strikesystem, "build_strikesystem", tracked("strike-system"))
    monkeypatch.setattr(recruit_familyparticulars, "build_familyparticulars", tracked("family-particulars"))
    monkeypatch.setattr(content, "_baselines", {})

    async def check():
        for document in content.DOCUMENTS.values():
            await content.baseline(document)

    asyncio.run(check())
    assert calls == [("join-family", (), {}), ("about-us", (), {}), ("strike-system", (), {}), ("family-particulars", (), {})]


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
        sections[0] += "x" * (4001 - sum(map(len, sections)))
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


def test_content_editor_remains_available_without_old_slash_group():
    assert not content.content.subcommands
    assert not any(getattr(item, "_command", None) for item in content.loader._loadables)
    assert "content_upload" in registered_functions
    assert "content_upload_submit" in registered_functions


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


def test_native_document_changed_fields_match_exact_approved_text():
    expected = [
        ('about-us', "We're an English-speaking", (
            "We're an English-speaking clan family based in the USA, with Clashers from around the gl"
            'obe. We use a game system that lets you take part in war while your base is upgrading.\n\n'
            '**Note:** None of our clans is a Family Friendly Clan. If one of your accounts needs a F'
            "amily Friendly Clan, join a clan outside Warriors United.\n\nHere's what we provide:\n:shie"
            'ld: 2 High-Level Tactical Clans\n:shield: 3 Flexible Fun War Clans\n:shield: 5 Official FW'
            'A Clans for Farmers\n:shield: CWL opportunities for everyone\n:shield: An Experienced Base'
            '-Building Team\n:shield: Experienced Attack Trainers'
        )),
        ('about-us', 'We look at each new recruit', (
            'We look at each new recruit case by case. We explain each clan type in your interview. T'
            'he requirements above are guides. Leadership makes the final decision.'
        )),
        ('about-us', '**Clash of Thrones', (
            '**Clash of Thrones (#Q889GPL)**\n**CoT Wildlings (#2YJVQUCYJ)**\n**Four and Twenty (#8CV0G'
            'PPR)**\n**The Horde (#2RRCJCI0)**\n**PlaneClashers (#9UGQ0GL)**\n\nFWA (Farm War Alliance) i'
            's an alliance of clans. The clans have organized wars, one after the other, for loot. Th'
            'e war result is decided before the war, and simple war plans tell you how to get that re'
            'sult. Heroes are not required.\n\nMinimum requirements: TH12 or higher, a war weight of 11'
            '5 or more, and all buildings built for your current TH level.'
        )),
        ('strike-system', '🛡️**WARRIORS UNITED**', (
            '🛡️**WARRIORS UNITED**🛡️ is an adult community with good morals and ethics. A little bant'
            'er and joking is fine, but we do not allow some things...\n\n**1.** No form of sexism, rac'
            'ism, religious discrimination, or gender discrimination will be tolerated. We ban you pe'
            'rmanently, without a warning, if we see this anywhere on this server.\n\n**2.** While cuss'
            'ing is allowed, do not cuss excessively or at someone. All such instances will be record'
            'ed. A warning will be issued to you for each instance.\n\n**3.** Do not post advertisement'
            's for free Nitro. We do not check if they are real, and we ban without a warning.\n\n**4.*'
            '* Respect other members and their privacy. If you send direct messages to someone again '
            'and again after they tell you to stop, you get a warning.\n\n**5.** When you post a messag'
            'e, image, GIF or sticker, always follow the Discord Terms of Service: https://discord.co'
            'm/terms. Not following Discord ToS will lead to a one-day mute, and a second instance wi'
            'll lead to a ban from the server.\n\nAfter two warnings: you get a one-day timeout.\nAfter '
            'three warnings: you get a one-week timeout.\nAfter four warnings: you are banned from the'
            ' server for good and removed from the family in CoC.'
        )),
        ('family-particulars', 'To be included in war', (
            'To be included in war, you must have GREEN ✅ 🛡️ (opt-in) as your War Status. FWA/No Stre'
            'ss is explained below.\n\nIf you cannot take part in war for a personal reason, or your He'
            'roes are upgrading in a clan that needs Heroes in war, set your War Status to RED ❌ 🛡️ ('
            'opt-out).\n\nIf you do not tell us or do not change your war availability in one of these '
            'cases, you get a strike in the Warriors United Strike System.\n\nIf you are in one of our '
            "FWA Clans or one of our No Stress Clans, it's 50v50 wars, so no matter what your base is"
            ' upgrading, you should be ✅ with your War Status.'
        )),
        ('family-particulars', 'Everyone must help fill', (
            'Everyone must help fill Defensive CCs. Fill the Defensive CC of the member below you wit'
            'h the troops they ask for. Do not leave one person to fill all of them.'
        )),
        ('family-particulars', 'Our Clan War General', (
            'Our Clan War General will provide a scripted War Plan detailing your war assignment. Do '
            'not assume that you attack your mirror. Wait for the War Plan before you attack. If ther'
            'e is no plan after a long time, ping the War General role of your clan and ask. Do not a'
            'ttack alone without a plan. You have 24 hours to plan and attack. Always attack for star'
            's, not for loot or Hero status (unless given specific direction by the War General).'
        )),
        ('family-particulars', 'Select **I understand - Continue**', (
            'Select **I understand - Continue** to confirm that you read the Family Particulars. Then'
            ' select Apply to open an application ticket.\n\nSelect only one application ticket option.'
        )),
    ]
    async def check():
        for key, prefix, expected_field in expected:
            nodes = content.text_nodes(await content.baseline(content.DOCUMENTS[key]))
            matches = [node.content for node in nodes if node.content.startswith(prefix)]
            assert matches == [expected_field]
    asyncio.run(check())
