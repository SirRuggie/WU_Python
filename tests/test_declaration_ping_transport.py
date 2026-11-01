import asyncio
from unittest.mock import patch
import pytest
from extensions.cwl_declaration_transport import (
    DeclarationPingTransport,
    PingRejected,
    PingUncertain,
)

CHANNEL = "234567890123456789"
USER = "123456789012345678"


class Response:
    def __init__(self, status=200, data=None):
        self.status = status
        self.data = data or {
            "id": "345678901234567890",
            "channel_id": CHANNEL,
            "nonce": "fixture",
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.data


class Session:
    calls = []
    response = Response()

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


@pytest.mark.parametrize(
    "allowed,test",
    [
        ({"parse": ["everyone"], "users": [], "roles": []}, False),
        ({"parse": [], "users": [], "roles": [USER]}, False),
        ({"parse": [], "users": [USER], "roles": []}, True),
        ({"parse": ["users"], "users": [USER], "roles": []}, False),
        ({"parse": [], "users": [USER, USER], "roles": []}, False),
    ],
)
def test_unsafe_mentions_never_reach_discord(allowed, test):
    async def run():
        with patch(
            "extensions.cwl_declaration_transport.aiohttp.ClientSession", Session
        ):
            Session.calls = []
            with pytest.raises(ValueError):
                await DeclarationPingTransport("fixture").send(
                    CHANNEL, {"allowed_mentions": allowed}, "fixture", test=test
                )
            assert Session.calls == []

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,error", [(403, PingRejected), (429, PingRejected), (500, PingUncertain)]
)
def test_post_is_never_retried(status, error):
    async def run():
        Session.calls = []
        Session.response = Response(status)
        with patch(
            "extensions.cwl_declaration_transport.aiohttp.ClientSession", Session
        ):
            with pytest.raises(error):
                await DeclarationPingTransport("fixture").send(
                    CHANNEL,
                    {"allowed_mentions": {"parse": [], "users": [USER], "roles": []}},
                    "fixture",
                )
        assert len(Session.calls) == 1
        assert Session.calls[0][1]["json"]["enforce_nonce"] is True

    asyncio.run(run())


def test_success_receipt_and_test_payload():
    async def run():
        Session.calls = []
        Session.response = Response()
        with patch(
            "extensions.cwl_declaration_transport.aiohttp.ClientSession", Session
        ):
            assert (
                await DeclarationPingTransport("fixture").send(
                    CHANNEL,
                    {"allowed_mentions": {"parse": [], "users": [], "roles": []}},
                    "fixture",
                    test=True,
                )
                == "345678901234567890"
            )
        assert len(Session.calls) == 1
        assert Session.calls[0][1]["json"]["allowed_mentions"] == {
            "parse": [],
            "users": [],
            "roles": [],
        }

    asyncio.run(run())
