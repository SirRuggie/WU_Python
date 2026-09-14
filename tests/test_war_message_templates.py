from hikari.impl import TextDisplayComponentBuilder as Text

from extensions.commands.fwa.message_templates import WarMessageTemplates

ROLE = "111222333"
FWA_ROLE = "444555666"
OPPONENT = "Some Clan"


def _texts(container):
    return [c for c in container.components if isinstance(c, Text)]


def test_win_header():
    components = WarMessageTemplates.win_message(OPPONENT, "Author", ROLE)
    container = components[0]
    texts = _texts(container)
    assert texts[0].content == "# ✅ WIN ✅"
    assert texts[1].content == f"## <@&{ROLE}> vs `{OPPONENT}`"


def test_lose_header():
    components = WarMessageTemplates.lose_message(OPPONENT, "Author", ROLE)
    container = components[0]
    texts = _texts(container)
    assert texts[0].content == "# ❌ LOSE ❌"
    assert texts[1].content == f"## <@&{ROLE}> vs `{OPPONENT}`"


def test_blacklisted_header():
    components = WarMessageTemplates.blacklisted_message(OPPONENT, "Author", ROLE, FWA_ROLE)
    container = components[0]
    texts = _texts(container)
    assert texts[0].content == "# \U0001f6e1️ BLACKLISTED CLAN \U0001f6e1️"
    assert texts[1].content == f"## <@&{ROLE}> vs `{OPPONENT}`"
    assert texts[2].content == "## ⚔️ **Switch to War Bases NOW!**"


def test_mismatch_header():
    components = WarMessageTemplates.mismatch_message(OPPONENT, "Author", ROLE)
    container = components[0]
    texts = _texts(container)
    assert texts[0].content == "# \U0001f926 MISMATCH \U0001f926"
    assert texts[1].content == f"## <@&{ROLE}> vs `{OPPONENT}`"


def test_win_body_after_header():
    container = WarMessageTemplates.win_message(OPPONENT, "Author", ROLE)[0]
    body = container.components[2:]
    assert len(body) == 9
    combined = "\n".join(
        c.content for c in body if isinstance(c, Text)
    )
    assert "First attack" in combined
    assert "Goal: 150 Stars" in combined
    assert body[-1].content == "-# 📣 *War declaration by Author*"


def test_lose_body_after_header():
    container = WarMessageTemplates.lose_message(OPPONENT, "Author", ROLE)[0]
    body = container.components[2:]
    assert len(body) == 9
    combined = "\n".join(
        c.content for c in body if isinstance(c, Text)
    )
    assert "First attack" in combined
    assert "Goal: 100 Stars" in combined
    assert body[-1].content == "-# 📣 *War declaration by Author*"


def test_blacklisted_body_after_header():
    container = WarMessageTemplates.blacklisted_message(OPPONENT, "Author", ROLE, FWA_ROLE)[0]
    body = container.components[3:]
    assert len(body) == 19
    combined = "\n".join(
        c.content for c in body if isinstance(c, Text)
    )
    assert "Enemy Intel" in combined
    assert "FWA POINT OBJECTIVES" in combined
    assert body[-1].content == "-# 📣 *War declaration by Author*"


def test_mismatch_body_after_header():
    container = WarMessageTemplates.mismatch_message(OPPONENT, "Author", ROLE)[0]
    body = container.components[2:]
    assert len(body) == 7
    combined = "\n".join(
        c.content for c in body if isinstance(c, Text)
    )
    assert "Attacking is optional" in combined
    assert "Do not change your War Base." in combined
    assert body[-1].content == "-# 📣 *War declaration by Author*"


def test_opponent_backticks_are_stripped():
    dirty_opponent = "Sneaky`Clan"
    components = WarMessageTemplates.win_message(dirty_opponent, "Author", ROLE)
    texts = _texts(components[0])
    assert texts[1].content == f"## <@&{ROLE}> vs `SneakyClan`"


def test_blacklisted_enemy_intel_backticks_are_stripped():
    dirty_opponent = "Sneaky`Clan"
    components = WarMessageTemplates.blacklisted_message(dirty_opponent, "Author", ROLE, FWA_ROLE)
    texts = _texts(components[0])
    intel_text = next(t.content for t in texts if "Enemy Intel" in t.content)
    assert "Sneaky`Clan" not in intel_text
    assert "SneakyClan" in intel_text
