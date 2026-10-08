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


def test_recovery_backups_keep_baseline_and_latest(tmp_path):
    import sqlite3
    from utils.gold_loot import backup_database
    path = tmp_path / 'loot.db'
    db = connect(path)
    with db:
        db.execute("INSERT INTO session VALUES ('#CLAN', 'WU', 'start')")
        db.execute("INSERT INTO players VALUES ('#ABC', 'Player', 1000, 1500, 'start', 'later')")
    backup_database(db)
    with db:
        save_sample(db, player(1900), 'new')
    backup_database(db)
    db.close()
    for name, expected in [('baseline', 1500), ('latest', 1900)]:
        with sqlite3.connect(tmp_path / 'loot.db.backups' / (name + '.sqlite3')) as backup:
            assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert backup.execute('SELECT baseline, latest FROM players').fetchone() == (1000, expected)


def test_abrupt_process_exit_rolls_back_uncommitted_write(tmp_path):
    import subprocess
    import sys
    path = tmp_path / 'loot.db'
    db = connect(path)
    with db:
        db.execute("INSERT INTO session VALUES ('#CLAN', 'WU', 'start')")
        db.execute("INSERT INTO players VALUES ('#ABC', 'Player', 1000, 1500, 'start', 'later')")
    db.close()
    code = """import sqlite3, os, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute('BEGIN IMMEDIATE')
conn.execute('UPDATE players SET latest=9999')
os._exit(0)
"""
    subprocess.run([sys.executable, '-c', code, str(path)], check=True)
    db = connect(path)
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert tuple(db.execute('SELECT baseline, latest FROM players').fetchone()) == (1000, 1500)
    db.close()
