"""FWA_WAR_BASE / FWA_ACTIVE_WAR_BASE stay delivery-optimized after Manage FWA
Data loads them from Mongo.

Regression for the exact pattern behind the Cloudinary overage: Mongo holds
the raw upload URLs, but build_fwa_management_screen used to copy them
straight into the in-memory dicts, overwriting the size-capped values
main.py seeded at startup, so every FWA base was served full-size again
until restart.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from extensions.commands.clan.dashboard import fwa_data
from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE
from utils.media_urls import DETAIL, optimized

BASE = "https://wu-media.ruggie.zone"
RAW_WAR = f"{BASE}/fwa/bases/th16/war.abc1234567.jpg"
RAW_ACTIVE = f"{BASE}/fwa/bases/th16/active.abc1234567.jpg"


@pytest.fixture(autouse=True)
def restore_fwa_globals():
    """The dicts are module-level state shared across the whole test run."""
    war_before = dict(FWA_WAR_BASE)
    active_before = dict(FWA_ACTIVE_WAR_BASE)
    yield
    FWA_WAR_BASE.clear()
    FWA_WAR_BASE.update(war_before)
    FWA_ACTIVE_WAR_BASE.clear()
    FWA_ACTIVE_WAR_BASE.update(active_before)


def _fake_ctx():
    return MagicMock()


async def _fake_get_fwa_data(mongo):
    return {
        "fwa_base_links": {},
        "base_information": {},
        "base_upgrade_notes": {},
        "war_base_images": {"th16": RAW_WAR},
        "active_base_images": {"th16": RAW_ACTIVE},
    }


def test_dashboard_load_keeps_the_dicts_delivery_optimized(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", BASE)
    monkeypatch.setenv("R2_IMAGE_TRANSFORMS", "true")
    monkeypatch.setattr(fwa_data, "get_fwa_data", _fake_get_fwa_data)

    # Seed the dicts as main.py would at startup.
    FWA_WAR_BASE["th16"] = optimized(RAW_WAR, width=DETAIL)
    FWA_ACTIVE_WAR_BASE["th16"] = optimized(RAW_ACTIVE, width=DETAIL)

    asyncio.run(fwa_data.build_fwa_management_screen(ctx=_fake_ctx(), mongo=None))

    expected_war = optimized(RAW_WAR, width=DETAIL)
    expected_active = optimized(RAW_ACTIVE, width=DETAIL)

    assert FWA_WAR_BASE["th16"] == expected_war
    assert "/cdn-cgi/image/" in FWA_WAR_BASE["th16"]
    assert FWA_WAR_BASE["th16"] != RAW_WAR

    assert FWA_ACTIVE_WAR_BASE["th16"] == expected_active
    assert "/cdn-cgi/image/" in FWA_ACTIVE_WAR_BASE["th16"]
    assert FWA_ACTIVE_WAR_BASE["th16"] != RAW_ACTIVE


def test_dashboard_load_is_a_no_op_wrap_when_transforms_are_off(monkeypatch):
    monkeypatch.delenv("R2_IMAGE_TRANSFORMS", raising=False)
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", BASE)
    monkeypatch.setattr(fwa_data, "get_fwa_data", _fake_get_fwa_data)

    FWA_WAR_BASE["th16"] = RAW_WAR
    FWA_ACTIVE_WAR_BASE["th16"] = RAW_ACTIVE

    asyncio.run(fwa_data.build_fwa_management_screen(ctx=_fake_ctx(), mongo=None))

    assert FWA_WAR_BASE["th16"] == RAW_WAR
    assert FWA_ACTIVE_WAR_BASE["th16"] == RAW_ACTIVE
