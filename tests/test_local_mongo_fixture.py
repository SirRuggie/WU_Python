import pytest
from local_mongo_fixture import fixture_uri


@pytest.mark.parametrize("value", [None, ""])
def test_missing_fixture_is_never_inferred(value):
    assert fixture_uri(value) is None


@pytest.mark.parametrize("port", [27154, 27161])
def test_explicit_owned_loopback_port_can_be_selected(port):
    assert fixture_uri(f"mongodb://127.0.0.1:{port}") == f"mongodb://127.0.0.1:{port}"


@pytest.mark.parametrize("value", [
    "mongodb://production.example:27161", "mongodb+srv://127.0.0.1",
    "mongodb://localhost:27161", "mongodb://127.0.0.1:27017",
    "mongodb://127.0.0.1:8767", "mongodb://127.0.0.1:27170",
    "mongodb://user:password@127.0.0.1:27161",
    "mongodb://127.0.0.1:27161/production", "mongodb://127.0.0.1:27161?directConnection=true",
    "mongodb://127.0.0.1:27161#fragment", "mongodb://127.0.0.1:not-a-port",
])
def test_nonfixture_endpoint_is_rejected_before_any_client_is_created(value):
    with pytest.raises(ValueError):
        fixture_uri(value)
