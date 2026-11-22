"""Advisory response text is distinct from real ticket testing warnings."""
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from cwl_web import manage_tickets

class TicketHintTests(unittest.IsolatedAsyncioTestCase):
    async def test_advisories_are_hints_without_warning_or_config_mutation(self):
        cfg = {"main_candidate_parent": 123, "unrelated": "retained"}
        before = dict(cfg)
        db = SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value=cfg)))
        @asynccontextmanager
        async def mongo(_):
            yield db
        rollout=SimpleNamespace(phase="legacy",valid=True,desk_intake=False)
        with patch.object(manage_tickets, "require_manage", AsyncMock()), patch.object(manage_tickets,"mongo",mongo), patch.object(manage_tickets,"get_rollout",AsyncMock(return_value=rollout)):
            for part in ("main", "fwa", "desk"):
                with self.subTest(part=part):
                    response=await manage_tickets.settings(SimpleNamespace(match_info={"part":part}))
                    body=json.loads(response.text)
                    self.assertIn("hint",body)
                    self.assertNotIn("warning",body)
                    if part=="desk": self.assertEqual(body["hint"],"Staff threads use the Main staff channel.")
                    else: self.assertTrue(body["hint"].startswith("The recruit channel"))
        self.assertEqual(cfg,before)

    async def test_test_window_remains_a_real_warning(self):
        from extensions.commands.tickets import testing_service
        from cwl_web import server_management
        @asynccontextmanager
        async def mongo(_):
            yield object()
        with patch.object(manage_tickets,"require_manage",AsyncMock(return_value={})), patch.object(manage_tickets,"mongo",mongo), patch.object(testing_service,"test_mongo",lambda db:db), patch.object(testing_service,"active_window",AsyncMock(return_value={"allowed_user_ids":[]})), patch.object(server_management,"allowed",AsyncMock(return_value=False)):
            response=await manage_tickets.testing(object())
        body=json.loads(response.text)
        self.assertEqual(body["warning"],"Test window is open.")
        self.assertNotIn("hint",body)
