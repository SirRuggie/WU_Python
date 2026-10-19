import asyncio
from unittest.mock import AsyncMock,patch
import pytest
from cwl_web.providers import LiveProviders,ProviderUnavailable

def test_union_without_conflict_exclusion():
 async def run():
  ck=[{'player_tag':'#Q2Y','user_id':'100','is_verified':False},{'player_tag':'#G2Y','user_id':'999'}]
  cp=[{'tag':'#Q2Y','userId':'100','verified':True},{'tag':'#G2Y','userId':'100'},{'tag':'#P2Y','userId':'100'}]
  with patch('cwl_web.providers._lookup_shared_links',AsyncMock(return_value=ck)),patch('cwl_web.providers._lookup_clashperk_links',AsyncMock(return_value=cp)):
   provider=LiveProviders(coc_token='unused')
   assert await provider.linked_tags('100')=={'#Q2Y':True,'#G2Y':False,'#P2Y':False}
   assert await provider.linked_owner('#P2Y')=='100'
   assert await provider.linked_owner('#G2Y') is None
 asyncio.run(run())

@pytest.mark.parametrize('ck,cp',[(None,[]),([],None),(None,None)])
def test_outage_is_not_an_empty_account_list(ck,cp):
 async def run():
  with patch('cwl_web.providers._lookup_shared_links',AsyncMock(return_value=ck)),patch('cwl_web.providers._lookup_clashperk_links',AsyncMock(return_value=cp)):
   with pytest.raises(ProviderUnavailable):await LiveProviders(coc_token='unused').linked_tags('100')
 asyncio.run(run())
