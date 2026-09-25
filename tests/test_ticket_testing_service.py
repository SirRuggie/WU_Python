import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from extensions.commands.tickets import testing_service


class Collection:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.deleted = []

    async def find_one(self, query, *_args):
        row = self.rows.get(query.get("_id"))
        if row is None or any(row.get(key) != value for key, value in query.items() if key != "_id"):
            return None
        return dict(row)

    async def delete_one(self, query):
        self.deleted.append(query)
        return SimpleNamespace(deleted_count=1)

    async def delete_many(self, query):
        self.deleted.append(query)
        return SimpleNamespace(deleted_count=1)

    async def update_one(self, query, update, **_kwargs):
        self.rows.setdefault(query["_id"], {"_id": query["_id"]}).update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1)


class Scope:
    is_ticket_test_scope = True

    def __init__(self, parent):
        self.ticket_automation_state = Collection({"test_parents": parent})
        self.tickets = Collection()
        self.ticket_creation_state = Collection()
        self.ticket_open_slots = Collection()


class Rest:
    def __init__(self, channels):
        self.channels = channels
        self.deleted = []
        self.role_mutations = []

    async def fetch_channel(self, channel_id):
        return self.channels[channel_id]

    async def delete_channel(self, channel_id, **_kwargs):
        self.deleted.append(channel_id)

    async def edit_member(self, *args, **kwargs):
        self.role_mutations.append((args, kwargs))


PARENTS = {"_id": "test_parents", "mode": "test", "guild_id": 10,
           "marker": "owned-test-parents", "candidate_parent_id": 20,
           "staff_parent_id": 21}


def test_rest_guard_refuses_unknown_member_mutation():
    scoped = Scope(PARENTS)
    rest = Rest({})
    guarded = testing_service.TestRESTGuard(rest, scoped)
    with pytest.raises(PermissionError):
        asyncio.run(guarded.edit_member(10, 30, roles=[123]))
    assert rest.role_mutations == []


def test_cleanup_refuses_forged_live_thread_id():
    scoped = Scope(PARENTS)
    rest = Rest({101: SimpleNamespace(id=101, name="live-main-1", parent_id=20, guild_id=10)})
    bot = SimpleNamespace(rest=rest)
    row = {"_id": "ticket_101", "mode": "test", "location": {
        "id": 101, "staff_space_id": 102, "public_parent_id": 20,
        "staff_parent_id": 21,
    }, "cleanup_at": datetime.now(timezone.utc)}
    with pytest.raises(RuntimeError, match="unverified parent or name"):
        asyncio.run(testing_service._cleanup_row(bot, scoped, "ticket", row))
    assert rest.deleted == []
    assert scoped.tickets.deleted == []


def test_counter_and_names_are_separate_from_live():
    from extensions.commands.tickets import thread_service
    assert testing_service.number_label(1) == "TEST001"
    test_names = thread_service.thread_names("main", 1, "Applicant", test=True)
    live_names = thread_service.thread_names("main", 1, "Applicant")
    assert "TEST001" in test_names[0]
    assert "TEST001" in test_names[1]
    assert "TEST001" not in live_names[0]


def test_test_ticket_creation_then_simulated_approval_stays_in_scope(monkeypatch):
    import hikari
    from extensions.commands import ticket_runtime
    from extensions.commands.tickets import account_sync, console, resolve, store, thread_service

    scoped = Scope(PARENTS)
    scoped.ticket_setup = Collection()
    scoped.ticket_automation_state.rows[testing_service.WINDOW_ID] = {
        "_id": testing_service.WINDOW_ID, "mode": "test", "guild_id": 10,
        "generation": "window-1",
        "allowed_user_ids": [30], "allowed_role_ids": [], "allow_admins": True,
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
        "cleanup_at": datetime(2099, 1, 2, tzinfo=timezone.utc),
    }
    slot = ticket_runtime.SlotClaim(True, "owner", {
        "_id": "ticket-open:30:main", "mode": "test", "state": "reserved",
        "window_generation": "window-1",
        "route": "thread", "guild_id": 10, "user_id": 30, "ticket_type": "main",
        "workflow_id": "thread:30:main", "rollout_revision": 1,
    })
    saved = {}

    async def none(*_args, **_kwargs):
        return None

    async def no_open(*_args, **_kwargs):
        return None

    async def claim(*_args, **_kwargs):
        return "creator", {"_id": "thread:30:main", "mode": "test",
            "window_generation": "window-1", "ticket_type": "main", "ticket_number": 1,
            "cleanup_at": datetime(2099, 1, 2, tzinfo=timezone.utc)}, False

    async def pair(**_kwargs):
        return SimpleNamespace(id=101), SimpleNamespace(id=102), {
            "ticket_number": 1, "window_generation": "window-1",
            "cleanup_at": datetime(2099, 1, 2, tzinfo=timezone.utc),
        }

    async def insert(_mongo, ticket):
        saved.update(ticket)
        return dict(ticket)

    async def finish(*_args, **_kwargs):
        return True

    async def bind(*_args, **_kwargs):
        return {"state": "open"}

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("production side effect reached")

    monkeypatch.setattr(thread_service, "ensure_creation_indexes", none)
    monkeypatch.setattr(thread_service, "validate_thread_parents", none)
    monkeypatch.setattr(thread_service, "_committed_ticket_for_creation_state", no_open)
    monkeypatch.setattr(thread_service, "_claim_creation", claim)
    monkeypatch.setattr(thread_service, "_ensure_live_thread_pair", pair)
    monkeypatch.setattr(thread_service.store, "find_open_for_applicant", no_open)
    monkeypatch.setattr(thread_service.store, "insert_one", insert)
    monkeypatch.setattr(thread_service, "_finish_committed_creation", finish)
    monkeypatch.setattr(thread_service, "_send_ticket_creation_dm", forbidden)
    monkeypatch.setattr(console, "deliver_staff_identity_context", none)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", forbidden)
    monkeypatch.setattr(ticket_runtime, "bind_open_slot", bind)
    monkeypatch.setattr(account_sync, "configured_coc_client", lambda: None)
    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=99), rest=SimpleNamespace())
    config = {"ticket_target_guild_id": 10, "main_candidate_parent": 20,
              "main_staff_parent": 21, "main_thread_recruiter_role": 40}

    created = asyncio.run(thread_service.create_live_thread_ticket(
        bot=bot, mongo=scoped, guild_id=10, user_id=30,
        username="Applicant", display_name=None, ticket_type="main",
        config=config, open_slot_claim=slot,
    ))
    assert created.ticket["mode"] == "test"
    assert created.ticket["cleanup_at"] == datetime(2099, 1, 2, tzinfo=timezone.utc)
    names = thread_service.thread_names(
        "main", created.ticket["ticket_number"], "Applicant", test=True,
    )
    assert all("TEST001" in name for name in names)

    async def recruiter(*_args, **_kwargs):
        return True

    async def read_ticket(*_args, **_kwargs):
        return dict(saved)

    async def transition(_mongo, _ticket_id, **kwargs):
        assert _mongo is scoped
        assert kwargs["to_status"] == "approved"
        decided = {**saved, "status": "approved"}
        return store.Transition(store.WON, decided)

    scheduled = []
    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve.store, "find_one", read_ticket)
    monkeypatch.setattr(resolve.store, "transition", transition)
    monkeypatch.setattr(resolve, "_schedule_resolution_effects", lambda bot, mongo, doc: scheduled.append((bot, mongo, doc)))
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", forbidden)
    monkeypatch.setattr(resolve.account_sync, "sync_ticket_accounts", forbidden)
    member = SimpleNamespace(id=40, guild_id=10, role_ids=(), permissions=hikari.Permissions.ADMINISTRATOR)
    decision = asyncio.run(resolve.approve_ticket(
        bot, scoped, ticket_id=created.ticket["_id"], member=member,
        actor_name="Tester", coc_client=None,
    ))
    assert decision.won
    assert scheduled[0][1] is scoped
    assert isinstance(scheduled[0][0].rest, testing_service.TestRESTGuard)


def test_old_window_decision_cannot_write_in_new_window(monkeypatch):
    import hikari
    from extensions.commands.tickets import resolve, store

    scoped = Scope(PARENTS)
    scoped.ticket_automation_state.rows[testing_service.WINDOW_ID] = {
        "_id": testing_service.WINDOW_ID, "mode": "test", "guild_id": 10,
        "generation": "new-window", "allowed_user_ids": [30], "allow_admins": True,
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
    }
    ticket = {"_id": "ticket_101", "mode": "test", "window_generation": "old-window",
              "venue": "thread", "status": "open", "type": "ticket", "runtime": "thread_v2"}

    async def recruiter(*_args, **_kwargs):
        return True

    async def read_ticket(*_args, **_kwargs):
        return ticket

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("stale window wrote a ticket")

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve.store, "find_one", read_ticket)
    monkeypatch.setattr(resolve.store, "transition", forbidden)
    member = SimpleNamespace(id=30, guild_id=10, role_ids=(), permissions=hikari.Permissions.ADMINISTRATOR)
    result = asyncio.run(resolve.approve_ticket(
        SimpleNamespace(rest=SimpleNamespace()), scoped,
        ticket_id="ticket_101", member=member, actor_name="Tester",
    ))
    assert result.outcome == store.BLOCKED


def test_actual_opening_delivery_reuses_questions_and_deduplicates():
    from extensions.commands.tickets import thread_service
    from extensions.commands.tickets import schema

    class Iterator:
        def __init__(self, values):
            self.values = values

        async def collect(self, _type):
            return list(self.values)

    class OpeningRest(Rest):
        def __init__(self):
            super().__init__({
                20: SimpleNamespace(id=20, guild_id=10, topic=PARENTS["marker"]),
                21: SimpleNamespace(id=21, guild_id=10, topic=PARENTS["marker"]),
                101: SimpleNamespace(id=101, name="🆕 main-TEST001-applicant", parent_id=20, guild_id=10),
                102: SimpleNamespace(id=102, name="🆕 staff-main-TEST001-applicant", parent_id=21, guild_id=10),
            })
            self.messages = {101: [], 102: []}

        def fetch_messages(self, channel_id):
            return Iterator(self.messages[channel_id])

        async def fetch_guild(self, _guild_id):
            return SimpleNamespace(make_icon_url=lambda: None)

        async def create_message(self, channel_id, **kwargs):
            message = SimpleNamespace(id=sum(map(len, self.messages.values())) + 1,
                                      author=SimpleNamespace(id=99),
                                      components=kwargs.get("components", ()),
                                      content=kwargs.get("content", ""),
                                      kwargs=kwargs)
            self.messages[channel_id].append(message)
            return message

    scoped = Scope(PARENTS)
    rest = OpeningRest()
    guarded = testing_service.TestRESTGuard(rest, scoped)
    guarded._new_thread_ids.update({101, 102})
    ticket = schema.new_ticket_document(
        ticket_type="main", ticket_number=1, guild_id=10,
        public_thread_id=101, public_parent_id=20,
        staff_thread_id=102, staff_parent_id=21,
        user_id=30, username="Applicant",
    )
    ticket.update({"mode": "test", "recruiter_role_id": 40})
    asyncio.run(thread_service._deliver_opening_messages(guarded, ticket, bot_id=99))
    first_counts = {channel: len(messages) for channel, messages in rest.messages.items()}
    asyncio.run(thread_service._deliver_opening_messages(guarded, ticket, bot_id=99))
    assert {channel: len(messages) for channel, messages in rest.messages.items()} == first_counts
    public_text = str(rest.messages[101])
    staff_text = str(rest.messages[102])
    assert "Your age, time zone, and country" in public_text
    assert "TEST MODE" in public_text
    assert "#TEST001" in staff_text
    assert "Candidate cannot see" not in staff_text
    assert all(message.kwargs.get("role_mentions") is False
               for messages in rest.messages.values() for message in messages)


def test_cleanup_of_reused_applicant_lease_deletes_each_new_test_pair():
    scoped=Scope(PARENTS)
    channels={20:SimpleNamespace(id=20,guild_id=10,topic=PARENTS['marker']),
              21:SimpleNamespace(id=21,guild_id=10,topic=PARENTS['marker'])}
    for number in (1,2):
        channels[number*100+1]=SimpleNamespace(id=number*100+1,guild_id=10,parent_id=20,name=f'Main TEST00{number}')
        channels[number*100+2]=SimpleNamespace(id=number*100+2,guild_id=10,parent_id=21,name=f'Main TEST00{number} staff')
    rest=Rest(channels)
    async def check():
        for number in (1,2):
            row={'_id':'thread:30:main','mode':'test','window_generation':'window',
                 'ticket_number':number,'candidate_thread_id':number*100+1,
                 'staff_thread_id':number*100+2,'candidate_parent_id':20,'staff_parent_id':21}
            assert await testing_service._cleanup_row(SimpleNamespace(rest=rest),scoped,'lease',row)
    asyncio.run(check())
    assert rest.deleted==[101,102,201,202]


def test_expired_orphan_reservation_is_cleaned_without_discord_mutations():
    scoped=Scope(PARENTS)
    orphan={'_id':'ticket-open:30:main','mode':'test','state':'reserved',
            'workflow_id':'thread:30:main','owner_token':'orphan-owner',
            'window_generation':'old','cleanup_at':datetime(2000,1,1,tzinfo=timezone.utc)}
    class Cursor:
        def __init__(self,rows): self.rows=rows
        def limit(self,_):return self
        async def to_list(self,**_):return self.rows
    scoped.tickets.find=lambda query:Cursor([])
    scoped.ticket_creation_state.find=lambda query:Cursor([])
    scoped.ticket_open_slots.find=lambda query:Cursor([orphan])
    rest=Rest({})
    asyncio.run(testing_service.cleanup_due(SimpleNamespace(rest=rest),scoped))
    assert rest.deleted==[]
    assert scoped.ticket_open_slots.deleted==[{
        '_id':'ticket-open:30:main','mode':'test','state':'reserved',
        'owner_token':'orphan-owner','window_generation':'old'}]
