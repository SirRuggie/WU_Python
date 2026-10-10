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
            db.execute('INSERT INTO loot_events VALUES (?, ?, ?, ?)', (f'#{i:02}', 'time', 'farming', i*10))
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


def test_capped_account_counts_farming_and_ranked_once_after_restart(tmp_path):
    from utils.gold_loot import save_battles, RANKING_SQL
    path = tmp_path / 'loot.db'
    db = connect(path)
    start = '2026-10-08T13:47:41+00:00'
    with db:
        db.execute("INSERT INTO session VALUES ('#CLAN', 'WU', ?)", (start,))
        db.execute('INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)',
                   ('#ABC', 'Player', 2000000000, 2000000000, start, start))
    def battle(mode, time, amount):
        return dict(battleMode=mode, battleTime=time, lootedResources={'gold': amount})
    items = [battle('farming', '2026-10-08T14:21:38Z', 652325),
             battle('ranked', '2026-10-08T14:25:00Z', 100000),
             battle('legend', '2026-10-08T14:26:00Z', 50000),
             battle('farming', '2026-10-08T13:00:00Z', 999999)]
    with db:
        save_battles(db, '#ABC', items, 'later')
    db.close()
    db = connect(path)
    with db:
        save_battles(db, '#ABC', items, 'later')
        save_battles(db, '#ABC', [], 'later')
    assert db.execute(RANKING_SQL).fetchone()['looted'] == 802325
    assert db.execute('SELECT count(*) FROM loot_events').fetchone()[0] == 3
    db.close()


def test_bad_battle_response_does_not_partially_write(tmp_path):
    from utils.gold_loot import save_battles
    db = connect(tmp_path / 'loot.db')
    start = '2026-10-08T13:47:41+00:00'
    with db:
        db.execute('INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)',
                   ('#ABC', 'Player', 2000000000, 2000000000, start, start))
    items = [dict(battleMode='farming', battleTime='2026-10-08T14:21:38Z', lootedResources={'gold': 652325}),
             dict(battleMode='farming', battleTime='2026-10-08T14:23:38Z', lootedResources={})]
    with pytest.raises(ValueError):
        save_battles(db, '#ABC', items, 'later')
    assert db.execute('SELECT count(*) FROM loot_events').fetchone()[0] == 0
    db.close()


def test_family_expansion_preserves_scores_and_deduplicates(tmp_path):
    from utils.gold_loot import expand_rosters, RANKING_SQL
    db = connect(tmp_path / 'loot.db')
    start = '2026-10-08T13:47:41+00:00'
    with db:
        db.execute('INSERT INTO session VALUES (?, ?, ?)', ('#MAIN', 'Main', start))
        db.execute('INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)', ('#ABC', 'Player', 2000000000, 2000000000, start, start))
        db.execute('INSERT INTO loot_events VALUES (?, ?, ?, ?)', ('#ABC', start, 'farming', 652325))
    clans = [dict(tag='#MAIN', name='Main', memberList=[dict(tag='#ABC', name='Player')]),
             dict(tag='#FAMILY', name='Family', memberList=[dict(tag='#NEW', name='New'), dict(tag='#ABC', name='Player')])]
    expand_rosters(db, clans)
    expand_rosters(db, clans)
    assert db.execute('SELECT count(*) FROM players').fetchone()[0] == 2
    assert db.execute('SELECT count(*) FROM tracked_clans').fetchone()[0] == 2
    assert db.execute('SELECT baseline_at FROM players WHERE tag=?', ('#NEW',)).fetchone()[0] == start
    leader = db.execute(RANKING_SQL).fetchone()
    assert leader['tag'] == '#ABC' and leader['looted'] == 652325
    assert leader['baseline'] == 2000000000
    assert leader['clan_name'] == 'Main'
    db.close()


@pytest.mark.parametrize('bad',[None,{}, {'battleMode':'farming','battleTime':'2026-10-08T12:00:00','lootedResources':{'gold':10}}, {'battleMode':'farming','battleTime':'2026-10-08T12:00:00Z','lootedResources':None}])
def test_malformed_history_preserves_saved_loot(tmp_path,bad):
    from utils.gold_loot import save_battles
    db=connect(tmp_path/'malformed.db')
    with db:
        db.execute("INSERT INTO players VALUES ('#ONE','One',0,0,'2026-10-08T00:00:00+00:00','old')")
        db.execute("INSERT INTO loot_events VALUES ('#ONE','2026-10-08T01:00:00+00:00','farming',42)")
    with pytest.raises(ValueError):
        save_battles(db,'#ONE',[bad],'new')
    assert db.execute('SELECT gold FROM loot_events').fetchone()[0]==42
    assert db.execute('SELECT updated FROM players').fetchone()[0]=='old'
    db.close()
