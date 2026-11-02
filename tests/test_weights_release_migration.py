"""Release migration comparisons must not turn an empty-table allowance into a bypass."""

from copy import deepcopy
import sqlite3
import pytest
from tools import weights_release_migration as guard


@pytest.fixture
def database():
    db = sqlite3.connect(":memory:")
    db.executescript("""
      CREATE TABLE seasons(id INTEGER PRIMARY KEY,label TEXT);
      CREATE TABLE signups(tag TEXT PRIMARY KEY,player_name TEXT,pool TEXT);
      CREATE TABLE roster_entries(tag TEXT PRIMARY KEY,kept INTEGER);
      CREATE TABLE clan_player_weights(tag TEXT PRIMARY KEY,weight INTEGER,player_name TEXT,town_hall INTEGER);
      CREATE TABLE clan_player_weight_history(id INTEGER PRIMARY KEY,actor_id TEXT,weight INTEGER);
      CREATE TABLE clan_weight_war_lineups(clan_tag TEXT PRIMARY KEY,end_time TEXT NOT NULL,captured_at TEXT NOT NULL,lineup_json TEXT NOT NULL);
      CREATE TABLE miscellaneous(value);
      INSERT INTO seasons VALUES(1,'November');
      INSERT INTO signups VALUES('#G2Y','Ace','lazy');
      INSERT INTO roster_entries VALUES('#G2Y',1);
      INSERT INTO clan_player_weights VALUES('#G2Y',150000,'Ace',16);
      INSERT INTO clan_player_weight_history VALUES(1,'fixture-staff',150000);
      INSERT INTO clan_weight_war_lineups VALUES('#R2Y','2026-11-02','2026-11-01','{"order":{"#G2Y":1}}');
      INSERT INTO miscellaneous VALUES(1);
      INSERT INTO miscellaneous VALUES(X'00FF');
      INSERT INTO miscellaneous VALUES('literal');
    """)
    yield db
    db.close()


def install(db):
    db.executescript(guard.ACCEPTED_DDL)


def add_previous(db, tag="#R2Y"):
    db.execute(
        "INSERT INTO clan_weight_war_lineup_previous VALUES(?,?,?,?)",
        (tag, "2026-11-01", "2026-10-31", '{"order":{"#G2Y":1}}'),
    )
    db.commit()


def test_exact_first_creation_preserves_every_old_schema_row_and_count(database):
    before = guard.capture(database)
    protected_before = guard.capture_protected(
        database, lambda db: {"existing": [{"weight": 150000}]}
    )
    install(database)
    after = guard.capture(database)
    proof = guard.compare(before, after)
    assert proof["added_tables"] == [guard.TABLE]
    assert proof["created_empty_predecessor"] is True and proof["previous_rows"] == 0
    assert proof["existing_tables_verified"] == len(before["tables"])
    assert (
        guard.capture_protected(database, lambda db: {"existing": [{"weight": 150000}]})
        == protected_before
    )
    assert (
        guard.compare(guard.capture(database), guard.capture(database))["added_tables"]
        == []
    )


def test_existing_predecessor_is_captured_raw_and_must_stay_exact(database):
    install(database)
    add_previous(database)
    old = {"other": [{"actor": "staff"}]}
    included = guard.capture_protected(database, lambda db: old)
    assert old == {"other": [{"actor": "staff"}]}
    assert included[guard.TABLE] == [
        {
            "clan_tag": "#R2Y",
            "end_time": "2026-11-01",
            "captured_at": "2026-10-31",
            "lineup_json": '{"order":{"#G2Y":1}}',
        }
    ]
    assert (
        guard.compare(guard.capture(database), guard.capture(database))["previous_rows"]
        == 1
    )
    assert guard.capture_protected(database, lambda db: included) == included
    with pytest.raises(guard.MigrationGuardError, match="disagree"):
        guard.capture_protected(database, lambda db: {guard.TABLE: []})


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "extra",
    ["unrelated_empty", "clan_weight_war_lineup_previous_backup", 'quoted"empty'],
)
def test_rejects_unrelated_empty_table_even_alongside_the_expected_migration(
    database, existing, extra
):
    if existing:
        install(database)
    before = guard.capture(database)
    install(database)
    database.execute('CREATE TABLE "' + extra.replace('"', '""') + '"(value TEXT)')
    with pytest.raises(guard.MigrationGuardError, match="addition"):
        guard.compare(before, guard.capture(database))


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE clan_weight_war_lineup_previous(clan_tag TEXT,end_time TEXT NOT NULL,captured_at TEXT NOT NULL,lineup_json TEXT NOT NULL)",
        "CREATE TABLE clan_weight_war_lineup_previous(clan_tag TEXT PRIMARY KEY,end_time TEXT,captured_at TEXT NOT NULL,lineup_json TEXT NOT NULL)",
        "CREATE TABLE clan_weight_war_lineup_previous(clan_tag TEXT PRIMARY KEY,end_time TEXT NOT NULL,captured_at TEXT NOT NULL,lineup_json TEXT NOT NULL,extra TEXT)",
        "CREATE TABLE clan_weight_war_lineup_previous(clan_tag TEXT PRIMARY KEY COLLATE NOCASE,end_time TEXT NOT NULL,captured_at TEXT NOT NULL,lineup_json TEXT NOT NULL)",
        "CREATE TABLE clan_weight_war_lineup_previous(clan_tag TEXT PRIMARY KEY,end_time TEXT NOT NULL,captured_at TEXT NOT NULL,lineup_json TEXT NOT NULL) WITHOUT ROWID",
    ],
)
def test_only_the_exact_accepted_ddl_is_allowed(database, ddl):
    before = guard.capture(database)
    database.execute(ddl)
    with pytest.raises(guard.MigrationGuardError, match="DDL"):
        guard.compare(before, guard.capture(database))


def test_new_table_must_start_empty_not_backfill_a_prior_lineup(database):
    before = guard.capture(database)
    install(database)
    add_previous(database)
    with pytest.raises(guard.MigrationGuardError, match="empty"):
        guard.compare(before, guard.capture(database))


def test_missing_migration_cannot_approve_old_code(database):
    with pytest.raises(guard.MigrationGuardError, match="missing"):
        guard.compare(guard.capture(database), guard.capture(database))


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE clan_player_weights SET weight=155000",
        "UPDATE clan_player_weights SET player_name='Other'",
        "UPDATE clan_player_weights SET town_hall=17",
        "UPDATE clan_player_weight_history SET actor_id='another-staff'",
        "UPDATE roster_entries SET kept=0",
        "UPDATE signups SET pool='main'",
        "UPDATE seasons SET label='December'",
        "UPDATE clan_weight_war_lineups SET captured_at='different'",
        "DELETE FROM signups",
        "INSERT INTO signups VALUES('#P2Y','New','main')",
        "UPDATE miscellaneous SET value=1.0 WHERE typeof(value)='integer'",
        "UPDATE miscellaneous SET value=X'00FE' WHERE typeof(value)='blob'",
    ],
)
def test_no_weight_neighbouring_field_staff_or_other_old_row_change_is_allowed(
    database, sql
):
    before = guard.capture(database)
    install(database)
    database.execute(sql)
    with pytest.raises(guard.MigrationGuardError, match="rows/counts"):
        guard.compare(before, guard.capture(database))


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE clan_player_weights ADD COLUMN neighbouring TEXT",
        "CREATE INDEX unrelated_old_index ON signups(pool)",
        "CREATE TRIGGER unrelated_old_trigger AFTER UPDATE ON signups BEGIN SELECT 1; END",
        "CREATE VIEW unrelated_view AS SELECT * FROM signups",
        "DROP TABLE miscellaneous",
    ],
)
def test_no_other_schema_objects_or_columns_may_change(database, sql):
    before = guard.capture(database)
    install(database)
    database.execute(sql)
    with pytest.raises(guard.MigrationGuardError):
        guard.compare(before, guard.capture(database))


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE INDEX bad_previous_index ON clan_weight_war_lineup_previous(end_time)",
        "CREATE TRIGGER bad_previous_trigger AFTER INSERT ON clan_weight_war_lineup_previous BEGIN SELECT 1; END",
    ],
)
def test_extra_objects_on_the_new_table_are_not_smuggled_through(database, sql):
    before = guard.capture(database)
    install(database)
    database.execute(sql)
    with pytest.raises(guard.MigrationGuardError, match="DDL"):
        guard.compare(before, guard.capture(database))


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE clan_weight_war_lineup_previous SET captured_at='changed'",
        "UPDATE clan_weight_war_lineup_previous SET lineup_json='{}'",
        "DELETE FROM clan_weight_war_lineup_previous",
        "INSERT INTO clan_weight_war_lineup_previous VALUES('#P2Y','new','new','{}')",
    ],
)
def test_existing_previous_rows_cannot_change_or_disappear(database, sql):
    install(database)
    add_previous(database)
    before = guard.capture(database)
    database.execute(sql)
    with pytest.raises(guard.MigrationGuardError, match="rows/counts"):
        guard.compare(before, guard.capture(database))


def test_capture_and_protected_augmentation_are_read_only_and_keep_caller_transaction(
    database,
):
    database.execute("BEGIN")
    writes = {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_ALTER_TABLE,
    }
    database.set_authorizer(
        lambda action, *args: (
            sqlite3.SQLITE_DENY if action in writes else sqlite3.SQLITE_OK
        )
    )
    guard.capture(database)
    guard.capture_protected(database, lambda db: {"old": []})
    assert database.in_transaction
    database.set_authorizer(None)
    database.rollback()
    guard.capture(database)
    assert not database.in_transaction


def test_missing_or_tampered_captures_fail_closed(database):
    with pytest.raises(guard.MigrationGuardError):
        guard.capture(sqlite3.connect(":memory:"))
    with pytest.raises(guard.MigrationGuardError):
        guard.compare({}, {})
    before = guard.capture(database)
    install(database)
    after = guard.capture(database)
    broken = deepcopy(after)
    broken["tables"]["signups"]["count"] = 0
    with pytest.raises(guard.MigrationGuardError, match="checksum"):
        guard.compare(before, broken)
    with pytest.raises(guard.MigrationGuardError, match="Independent"):
        guard.compare(after, after)
    with pytest.raises(guard.MigrationGuardError, match="empty"):
        guard.capture_protected(database, lambda db: {})
