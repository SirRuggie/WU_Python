"""Mutation permission map. Unknown CWL writes fail closed."""
APP_ACTIONS = {
    **dict.fromkeys(('set_member_season', 'create_season', 'update_season', 'create_clan', 'lookup_clan', 'archive_clan', 'add_lineup', 'remove_lineup'), 'cwl_settings'),
    **dict.fromkeys(('staff_add_signup', 'staff_remove_signup'), 'cwl_signups'),
    **dict.fromkeys(('update_lineup_rules', 'bulk_assign_roster', 'update_roster_account', 'swap_roster', 'undo_roster', 'auto_preview', 'auto_apply', 'refresh_weights', 'arrival_check'), 'cwl_roster'),
    'publish_roster': 'cwl_publish',
    'withdraw_publication': 'cwl_publish',
}
MODULE_ACTIONS = {
    'staff_signup_changes': 'cwl_signups', 'staff_tag_signups': 'cwl_signups', 'signup_activity': 'cwl_signups',
    'manage_reminders': 'cwl_reminders', 'participation': 'cwl_results',
    'participation_sync': 'cwl_results', 'bonuses': 'cwl_bonuses',
    'bonus_raffle': 'cwl_bonuses', 'manage_bridge': 'cwl_send',
    'roster_images': 'cwl_send', 'announcements': 'cwl_send',
}


def mutation_permission(request):
    handler = request.match_info.handler
    name, module = handler.__name__, handler.__module__.rsplit('.', 1)[-1]
    if module == 'app':
        return APP_ACTIONS.get(name)
    if module in ('manage_bridge', 'bonus_raffle') and name in ('send', 'test_announcement'):
        return 'cwl_send'
    return MODULE_ACTIONS.get(module)
