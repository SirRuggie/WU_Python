import unittest
from cwl_web.manage_tickets import validated_settings

class TicketSettingsTests(unittest.TestCase):
    def test_only_native_fields_and_bounded_waits(self):
        self.assertEqual(validated_settings({'ticket_inactivity_minutes':1440,'ticket_archive_quiet_days':0}),{'ticket_inactivity_minutes':1440,'ticket_archive_quiet_days':0})
        for body in ({'ticket_target_guild_id':123},{'ticket_inactivity_minutes':True},{'ticket_inactivity_minutes':1},{'ticket_archive_quiet_days':366},{'main_candidate_parent':'bad'},{'ticket_staff_viewer_role_ids':[{}]}):
            with self.assertRaises(ValueError):validated_settings(body)

    def test_snowflakes_stay_exact_and_viewers_are_narrow(self):
        result=validated_settings({'main_thread_recruiter_role':'1003797104088592444','ticket_staff_viewer_role_ids':['1003797104088592444']})
        self.assertEqual(result['main_thread_recruiter_role'],1003797104088592444)
        self.assertEqual(result['ticket_staff_viewer_role_ids'],[1003797104088592444])
