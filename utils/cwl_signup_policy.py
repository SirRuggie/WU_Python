"""Current-clan CWL pool eligibility; historical clan labels are not restrictions."""
FWA_MAIN_MESSAGE = 'FWA accounts can only sign up for Lazy CWL. LAZY WAY OR NO WAY!'


def main_signup_error(account):
    if account.get('current_clan_type') == 'FWA':
        return 409, FWA_MAIN_MESSAGE
    if account.get('current_clan_tag') and account.get('family_clan_status') == 'unknown':
        return 503, 'Could not verify the current clan category. Refresh accounts before choosing Main CWL.'
    return None
