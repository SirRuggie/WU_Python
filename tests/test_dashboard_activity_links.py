import unittest
from cwl_web.app import login_destination

class ActivityLoginLinks(unittest.TestCase):
    def test_member_destinations_survive_login(self):
        for view in ('search', 'wars', 'events'):
            self.assertEqual(login_destination({'view': view, 'season': '3'}), '/' + view)

    def test_external_and_unknown_destinations_are_not_login_redirects(self):
        for view in ('https://evil.example', '//evil.example', 'not-a-page'):
            self.assertEqual(login_destination({'view': view}), '')
