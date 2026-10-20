import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.strikes import roles


@pytest.mark.parametrize(('error', 'expected'), [
    (hikari.NotFoundError('https://discord.com', {}, {}, 'Unknown Member'), []),
    (hikari.ForbiddenError('https://discord.com', {}, {}, 'Missing Access'), None),
])
def test_missing_member_has_no_roles_but_failed_check_stays_unknown(error, expected):
    bot = SimpleNamespace(rest=SimpleNamespace(fetch_member=AsyncMock(side_effect=error)))
    assert asyncio.run(roles(123, 456, bot)) == expected
