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


class SharedTicketContractTests(unittest.TestCase):
    def test_compatibility_exports_are_the_single_pure_owner(self):
        from cwl_web import manage_tickets as adapter
        from utils import ticket_settings as contract
        self.assertIs(adapter.FIELDS, contract.FIELDS)
        self.assertIs(adapter.validated_settings, contract.validated_settings)
        self.assertIs(adapter.history_values, contract.history_values)
        self.assertEqual(contract.validated_settings.__module__, 'utils.ticket_settings')

    def test_timer_bounds_and_rejections_preserve_exact_errors(self):
        from utils.ticket_settings import validated_settings
        for field, low, high, message in (
            ('ticket_inactivity_minutes', 1440, 525600,
             'Open-ticket wait must be 1 to 365 days in minutes.'),
            ('ticket_archive_quiet_days', 0, 365,
             'Archive wait must be 0 to 365 days.'),
        ):
            for value in (low, high):
                with self.subTest(field=field, value=value):
                    self.assertEqual(validated_settings({field: value}), {field: value})
            for value in (low - 1, high + 1, True, False, str(low), float(low), None):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError) as error:
                        validated_settings({field: value})
                    self.assertEqual(str(error.exception), message)

    def test_unknown_input_never_becomes_an_empty_valid_change(self):
        from utils.ticket_settings import validated_settings
        self.assertEqual(validated_settings({}), {})
        for values in (None, [], 'timers', True, {'unknown': 1}):
            with self.subTest(values=values), self.assertRaises(ValueError) as error:
                validated_settings(values)
            self.assertEqual(str(error.exception), 'Unknown ticket setting.')

    def test_snowflake_length_type_and_exact_precision(self):
        from utils.ticket_settings import validated_settings
        for value in ('1' * 15, '1003797104088592444', '9' * 22):
            self.assertEqual(validated_settings({'fwa_staff_parent': value}),
                             {'fwa_staff_parent': int(value)})
        for value in ('1' * 14, '1' * 23, ' 1003797104088592444', '-1003797104088592444',
                      1003797104088592444, True, None):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                validated_settings({'fwa_staff_parent': value})
            self.assertEqual(str(error.exception), 'Select a channel or role.')

    def test_viewer_order_duplicates_empty_and_limit_are_preserved(self):
        from utils.ticket_settings import validated_settings
        values = ['1003797104088592444', '7', '1003797104088592444']
        self.assertEqual(validated_settings({'ticket_staff_viewer_role_ids': values}),
                         {'ticket_staff_viewer_role_ids': list(map(int, values))})
        self.assertEqual(values, ['1003797104088592444', '7', '1003797104088592444'])
        for values in ([], ['7'] * 25):
            self.assertEqual(validated_settings({'ticket_staff_viewer_role_ids': values}),
                             {'ticket_staff_viewer_role_ids': list(map(int, values))})
        for values in (['7'] * 26, ('7',), '7', [7], [True], [''], ['-7'], None):
            with self.subTest(values=values), self.assertRaises(ValueError) as error:
                validated_settings({'ticket_staff_viewer_role_ids': values})
            self.assertEqual(str(error.exception), 'Select valid viewer roles.')

    def test_history_missing_defaults_and_unknown_parts_are_not_normalized(self):
        from utils.ticket_settings import history_values
        self.assertEqual(history_values({}, 'timers'),
                         {'ticket_inactivity_minutes': 10080, 'ticket_archive_quiet_days': 1})
        self.assertEqual(history_values({}, 'viewers'), {'ticket_staff_viewer_role_ids': []})
        self.assertEqual(history_values({}, 'other'), {
            'other_candidate_parent': '', 'other_staff_parent': '',
            'other_thread_recruiter_role': '',
        })
        cfg = {'main_candidate_parent': 0, 'main_staff_parent': 1003797104088592444,
               'main_thread_recruiter_role': None, 'unrelated': 'kept'}
        before = dict(cfg)
        self.assertEqual(history_values(cfg, 'main'), {
            'main_candidate_parent': '', 'main_staff_parent': '1003797104088592444',
            'main_thread_recruiter_role': '',
        })
        self.assertEqual(history_values({'ticket_staff_viewer_role_ids': [9, 9, 1]}, 'viewers'),
                         {'ticket_staff_viewer_role_ids': ['9', '9', '1']})
        self.assertEqual(cfg, before)
