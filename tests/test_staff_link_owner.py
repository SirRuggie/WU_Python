import unittest
from unittest.mock import patch,AsyncMock
from cwl_web.providers import LiveProviders,ProviderUnavailable
class OwnerLookupTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  other=patch('cwl_web.providers._lookup_clashperk_links',AsyncMock(return_value=[]))
  other.start()
  self.addCleanup(other.stop)
 async def test_reverse_lookup_normalizes_filters_and_deduplicates(self):
  provider=LiveProviders(coc_token='',mongo_uri='',routes={})
  rows=[{'player_tag':'P2Y','user_id':'123456789012345678'},{'player_tag':'#P2Y','user_id':'123456789012345678'},{'player_tag':'#G2Y','user_id':'other'}]
  with patch('cwl_web.providers._lookup_shared_links',AsyncMock(return_value=rows)) as lookup:
   self.assertEqual(await provider.linked_owner('p2y'),'123456789012345678')
   lookup.assert_awaited_once_with(player_tags=['#P2Y'])
 async def test_no_link_is_distinct_from_outage_or_conflicting_owners(self):
  provider=LiveProviders(coc_token='',mongo_uri='',routes={})
  with patch('cwl_web.providers._lookup_shared_links',AsyncMock(return_value=[])):
   self.assertIsNone(await provider.linked_owner('#P2Y'))
  for rows in [None,[{'player_tag':'#P2Y','user_id':'123456789012345678'},{'player_tag':'#P2Y','user_id':'223456789012345678'}]]:
   with patch('cwl_web.providers._lookup_shared_links',AsyncMock(return_value=rows)):
    if rows is None:
     with self.assertRaises(ProviderUnavailable):await provider.linked_owner('#P2Y')
    else:
     self.assertIsNone(await provider.linked_owner('#P2Y'))
