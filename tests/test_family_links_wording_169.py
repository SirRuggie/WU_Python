from tools.seed_server_roles import SEED_ROLES


def test_family_role_seed_preserves_approved_descriptions():
    rows = {row['label']: row for row in SEED_ROLES}
    assert rows['Lazy Clan Participant']['short_line'] == 'Get this role to see the LazyCWL signups channel.'
    assert rows['VC Participant']['short_line'] == 'A ping for members who want to talk.'
    assert len(rows) == 6
