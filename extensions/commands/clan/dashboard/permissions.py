"""Role checks shared by persistent clan-dashboard controls."""


async def require_dashboard_role(ctx, role_id: int, label: str) -> bool:
    member = getattr(ctx, "member", None) or getattr(ctx.interaction, "member", None)
    roles = member.get_roles() if member and hasattr(member, "get_roles") else ()
    if int(role_id) in {int(role.id) for role in roles}:
        return True
    await ctx.respond(f"❌ {label} role required.", ephemeral=True)
    return False


CLAN_CHILD_ACTIONS = frozenset({"clan_image_upload", "dashboard_image_submit", "add_clan_page", "add_clan", "add_clan_modal", "remove_clan_select", "clan_remove_menu", "remove_clan", "choose_clan_select", "clan_edit_menu", "edit_clan", "edit_thread", "update_logo", "logo_upload_guide", "logo_url_modal", "update_logo_modal", "back_to_clan_edit", "edit_roles", "edit_channels", "update_emoji", "emoji_url_modal", "emoji_from_logo", "update_emoji_modal", "update_general_info", "edit_general"})
FWA_CHILD_ACTIONS = frozenset({"fwa_image_upload", "fwa_back_to_main", "fwa_th_select", "fwa_update_link", "fwa_link_submit", "fwa_update_images", "fwa_image_urls", "fwa_images_submit", "fwa_update_descriptions", "fwa_th_select_return", "fwa_descriptions_submit", "fwa_upload_guide"})


def dashboard_guard_for(action_name: str):
    if action_name in CLAN_CHILD_ACTIONS:
        return 993015846442127420, "Clan Management"
    if action_name in FWA_CHILD_ACTIONS:
        return 993015846442127420, "FWA Representative"
    return None
