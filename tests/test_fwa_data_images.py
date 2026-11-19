"""Registry image cache remains delivery-optimized and management never mutates it."""
import asyncio
from unittest.mock import patch
from types import SimpleNamespace
import pytest
from utils import town_halls
from utils.constants import FWA_WAR_BASE,FWA_ACTIVE_WAR_BASE
from utils.media_urls import DETAIL,optimized
from utils.manage_operations_runtime import publish_base_image_snapshot
from extensions.commands.clan.dashboard import fwa_data
from test_town_halls_discord_bases_245 import bases_doc,GUILD_ID

@pytest.mark.parametrize('transforms',[True,False])
def test_registry_cache_optimizes_shared_images_without_management_side_effects(monkeypatch,transforms):
    base='https://wu-media.ruggie.zone'
    monkeypatch.setenv('R2_PUBLIC_BASE_URL',base)
    monkeypatch.setenv('R2_IMAGE_TRANSFORMS','true' if transforms else 'false')
    doc=bases_doc();doc['levels']['19']['bases'].update(war_image=base+'/fwa/bases/th19/war.abc.jpg',active_image=base+'/fwa/bases/th19/active.abc.jpg')
    monkeypatch.setattr(town_halls,'_snapshot',doc);monkeypatch.setattr(town_halls,'_snapshot_guild',str(GUILD_ID))
    old_war,old_active=dict(FWA_WAR_BASE),dict(FWA_ACTIVE_WAR_BASE)
    try:
        publish_base_image_snapshot(doc)
        before=dict(FWA_WAR_BASE),dict(FWA_ACTIVE_WAR_BASE)
        asyncio.run(fwa_data.build_fwa_management_screen(SimpleNamespace(),object()))
        assert before==(dict(FWA_WAR_BASE),dict(FWA_ACTIVE_WAR_BASE))
        assert FWA_WAR_BASE['th19']==FWA_WAR_BASE['th19_new']==optimized(doc['levels']['19']['bases']['war_image'],width=DETAIL)
        assert FWA_ACTIVE_WAR_BASE['th19']==FWA_ACTIVE_WAR_BASE['th19_new']
        assert ('/cdn-cgi/image/' in FWA_WAR_BASE['th19']) is transforms
    finally:
        FWA_WAR_BASE.clear();FWA_WAR_BASE.update(old_war);FWA_ACTIVE_WAR_BASE.clear();FWA_ACTIVE_WAR_BASE.update(old_active)
