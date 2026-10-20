from extensions.commands.strikes import replacement_line


def test_priority_and_unknown_weight_do_not_claim_a_match():
    text = replacement_line(1, {'player_tag': '#PC9YGL0JL', 'player_name': 'Filler',
        'current_clan_tag': '#2UVGQU9', 'active_strikes': 0, 'priority': 'replace_first',
        'note': 'My filler @everyone', 'weight': None, 'weight_difference': None})
    assert 'Replace first' in text and 'Weight unknown' in text
    assert '0 active strikes' in text and 'difference' not in text
    assert '@everyone' not in text


def test_weighted_high_priority_match_shows_distance():
    text = replacement_line(2, {'player_tag': '#PC9YGL0JL', 'current_clan_tag': '#2UVGQU9',
        'active_strikes': 2, 'replacement_priority': 'high', 'replacement_note': 'Inactive', 'weight': 114000, 'weight_difference': 1000})
    assert 'Inactive' in text
    assert 'High priority' in text and '114,000 weight' in text and 'difference 1,000' in text
