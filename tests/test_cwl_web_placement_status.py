import unittest
from cwl_web.placement_status import explain

class PlacementStatusTests(unittest.TestCase):
    def test_weight_and_setup_reasons_are_specific(self):
        account={'pool':'lazy','prefer_crystal_1_or_lower':False,'effective_weight':159000}
        clan={'archived':False,'pool':'lazy','capacity':15,'min_weight':160000,'max_weight':174000}
        self.assertIn('159k',explain(account,[clan],'no_eligible_rule'))
        self.assertIn('160k–under 174k',explain(account,[clan],'no_eligible_rule'))
        self.assertIn('capacity',explain(account,[clan|{'capacity':None}],'no_eligible_rule'))
        self.assertIn('signup pool',explain(account,[],'no_eligible_rule'))
        self.assertIn('place manually',explain(account,[clan],'missing_weight'))
        self.assertIn('Preview and apply',explain(account,[clan],'ready'))
