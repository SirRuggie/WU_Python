from types import SimpleNamespace
import pytest
from cwl_web.app import login_destination, saved_login_destination

@pytest.mark.parametrize('view', ['home','todo','signup','assignments'])
def test_known_member_destination(view):
    result=login_destination({'view':view,'season':'12','return_to':'https://evil.test'})
    assert result == '/?view='+view+('&season=12' if view in {'signup','assignments'} else '')

@pytest.mark.parametrize('value', ['https://evil.test', '//evil.test', '/?view=https://evil.test', '/?view=staff', '/?view=signup&season=bad'])
def test_untrusted_cookie_never_redirects_outside_member_pages(value):
    result=saved_login_destination(SimpleNamespace(cookies={'wu_login_page':value}))
    assert result in {'','/?view=signup'}

def test_saved_destination_roundtrip():
    assert saved_login_destination(SimpleNamespace(cookies={'wu_login_page':'/?view=assignments&season=12'}))=='/?view=assignments&season=12'
