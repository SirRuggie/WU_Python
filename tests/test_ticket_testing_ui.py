"""Focused rendering checks for the isolated ticket test panel."""

from __future__ import annotations

def _ui_module():
    from extensions.commands.tickets import testing
    return testing


def _labels(panel):
    return [
        component.label
        for child in panel[0].components
        for component in getattr(child, "components", ())
        if getattr(component, "label", None)
    ]


def _custom_ids(panel):
    return [
        component.custom_id
        for child in panel[0].components
        for component in getattr(child, "components", ())
        if getattr(component, "custom_id", None)
    ]


def test_allowed_tester_panel_has_only_test_open_actions():
    testing = _ui_module()
    panel = testing._panel("session", {}, admin=False)

    assert _labels(panel) == ["Open Main test ticket", "Open FWA test ticket"]
    assert _custom_ids(panel) == [
        "ticket_testing_open_main:session",
        "ticket_testing_open_fwa:session",
    ]


def test_admin_panel_uses_ticket_testing_action_namespace():
    testing = _ui_module()
    panel = testing._panel("session", {}, admin=True)
    ids = _custom_ids(panel)

    assert all(value.startswith("ticket_testing_") for value in ids)
    assert "ticket_testing_open_window:session" in ids
    assert "ticket_testing_users:session" in ids
    assert "ticket_testing_roles:session" in ids
    assert "ticket_testing_clear:session" in ids
