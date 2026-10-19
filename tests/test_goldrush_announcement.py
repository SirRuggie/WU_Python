from tools.announce_goldrush import winner_content


def row(user, gold, reached='2026-10-14T13:00:00+00:00'):
    return dict(user_id=str(user), gold=gold, reached_at=reached)


def test_announcement_tags_winning_account_owner():
    text = winner_content([row(123, 1200), row(456, 1000)])
    assert '<@123>' in text and '1,200 gold' in text
    assert '<@456>' not in text
    assert 'Go touch some grasss ffs' in text


def test_exact_tie_does_not_name_arbitrary_winner():
    text = winner_content([row(123, 1200), row(456, 1200)])
    assert 'exact tie' in text and '<@' not in text


def test_earlier_reached_score_wins():
    text = winner_content([row(123, 1200), row(456, 1200, '2026-10-14T13:01:00+00:00')])
    assert '<@123>' in text


def test_empty_and_zero_scores_have_no_winner():
    for rows in ([], [row(123, 0)]):
        assert 'no winner' in winner_content(rows)
