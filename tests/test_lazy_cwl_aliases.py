import asyncio
import hikari

from extensions.commands.fwa import lazy_cwl


class Member:
    def __init__(self, permissions): self.permissions = permissions
class Interaction:
    guild_id = 7
class Ctx:
    def __init__(self, permissions):
        self.member = Member(permissions); self.interaction = Interaction(); self.responses = []
    async def respond(self, message, ephemeral=False): self.responses.append((message, ephemeral))


def test_redirect_rejects_non_administrators_before_opening_dashboard():
    ctx = Ctx(hikari.Permissions.NONE)
    asyncio.run(lazy_cwl._redirect(ctx, object()))
    assert ctx.responses and ctx.responses[0][1] is True


def test_redirect_uses_shared_bound_dashboard_entry(monkeypatch):
    called = []
    async def open_dashboard(ctx, mongo, note=None): called.append((ctx, mongo, note))
    monkeypatch.setattr(lazy_cwl, "open_dashboard", open_dashboard)
    ctx = Ctx(hikari.Permissions.ADMINISTRATOR)
    asyncio.run(lazy_cwl._redirect(ctx, "mongo"))
    assert called == [(ctx, "mongo", lazy_cwl.MOVED_NOTICE)]
