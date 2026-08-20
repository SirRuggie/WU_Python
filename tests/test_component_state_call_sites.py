from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# These files own durable ticket mirrors or the separately bounded Goblin
# challenge and are intentionally allowed to touch the legacy collection.
ALLOWED_DIRECT_BUTTON_STORE = {
    Path("extensions/commands/tickets/store.py"),
    Path("extensions/commands/tickets/migrate.py"),
    # Read-only conflict detection prevents a canonical migration from cloning
    # a legacy-only or mismatched source ticket.
    Path("extensions/commands/tickets/legacy_migration.py"),
    Path("extensions/events/message/goblin_challenge.py"),
    Path("extensions/events/message/how_to_ping.py"),
    Path("extensions/commands/recruit/questions.py"),
}


def test_component_commands_do_not_bypass_expiring_state_store():
    violations = []
    for path in (ROOT / "extensions").rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative in ALLOWED_DIRECT_BUTTON_STORE:
            continue
        source = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(source.splitlines(), 1):
            if "mongo.button_store." in line and not line.lstrip().startswith("#"):
                violations.append(f"{relative}:{line_number}: {line.strip()}")

    assert violations == []
