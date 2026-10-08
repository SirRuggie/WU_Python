import pytest

from tools.gold_loot import connect, gold, leaderboard, save_sample


def player(value):
    return {'tag': '#ABC', 'name': 'Player',
            'achievements': [{'name': 'Gold Grab', 'value': value}]}


def test_persistent_delta_and_repeated_samples(tmp_path):
    path = tmp_path / 'loot.db'
    db = connect(path)
    with db:
        db.execute("INSERT INTO session VALUES ('#CLAN', 'Warriors United', 'start')")
        db.execute("INSERT INTO players VALUES ('#ABC', 'Player', 1000, 1000, 'start', 'start')")
        save_sample(db, player(1500), 'later')
        save_sample(db, player(1500), 'later-again')
    db.close()
    db = connect(path)
    assert db.execute('SELECT latest-baseline FROM players').fetchone()[0] == 500
    with pytest.raises(ValueError, match='decreased'):
        save_sample(db, player(900), 'bad')
    assert db.execute('SELECT latest FROM players').fetchone()[0] == 1500
    db.close()


def test_missing_counter_is_not_zero():
    with pytest.raises(ValueError):
        gold({'achievements': []})


def test_top_ten_sorted_by_gain(tmp_path, capsys):
    db = connect(tmp_path / 'loot.db')
    with db:
        db.execute("INSERT INTO session VALUES ('#CLAN', 'Warriors United', 'start')")
        for i in range(12):
            db.execute("INSERT INTO players VALUES (?, ?, ?, ?, 'start', 'later')",
                       (f'#{i:02}', f'Player{i:02}', 10000-i*100, 10000-i*90))
    leaderboard(db)
    text = capsys.readouterr().out
    assert text.index('Player11') < text.index('Player10')
    assert 'Player01' not in text
    assert 'Player00' not in text
    db.close()
