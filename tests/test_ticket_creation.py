import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest

from extensions import components as dispatcher
from extensions.commands.tickets import (
    account_sync,
    handlers,
    legacy_migration,
    schema,
    store,
    thread_service,
)


NOW = datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc)


def _ticket(*, public=101, staff=102, number=1, status="open", source=None):
    return schema.new_ticket_document(
        ticket_type="main",
        ticket_number=number,
        guild_id=10,
        public_thread_id=public,
        public_parent_id=20,
        staff_thread_id=staff,
        staff_parent_id=21,
        user_id=30,
        username="Applicant",
        created_at=NOW,
        status=status,
        source=source,
    )


class UpdateResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class AutomationStateCollection:
    def __init__(self, *, fail_updates=0):
        self.documents = {}
        self.fail_updates = fail_updates
        self.update_calls = 0

    async def update_one(self, query, update, **_kwargs):
        self.update_calls += 1
        if self.fail_updates:
            self.fail_updates -= 1
            raise TimeoutError("staff context queue unavailable")
        document = self.documents.setdefault(query["_id"], {"_id": query["_id"]})
        for key, value in update.get("$setOnInsert", {}).items():
            document.setdefault(key, value)
        document.update(update.get("$set", {}))
        for key, amount in update.get("$inc", {}).items():
            document[key] = int(document.get(key, 0)) + int(amount)
        for key in update.get("$unset", {}):
            document.pop(key, None)
        return UpdateResult(1)


class EmptyLazyIterator:
    async def to_list(self):
        return []


class CreationStateCollection:
    def __init__(self, document=None):
        self.document = dict(document) if document else None
        self.indexes = []
        self.fail_complete_once = False
        self.complete_failures = 0

    async def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))
        return kwargs.get("name")

    async def find_one(self, query):
        if self.document and self.document.get("_id") == query.get("_id"):
            return dict(self.document)
        return None

    async def insert_one(self, document):
        if self.document is not None:
            raise thread_service.DuplicateKeyError("duplicate")
        self.document = dict(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query, update, **_kwargs):
        if (
            self.fail_complete_once
            and update.get("$set", {}).get("state") == "complete"
            and self.complete_failures == 0
        ):
            self.complete_failures += 1
            raise TimeoutError("completion acknowledgement lost")
        if not self.document or self.document.get("_id") != query.get("_id"):
            return UpdateResult(0)
        if "state" in query and isinstance(query["state"], str):
            if self.document.get("state") != query["state"]:
                return UpdateResult(0)
        if "lease_owner" in query and self.document.get("lease_owner") != query["lease_owner"]:
            return UpdateResult(0)
        self.document.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            self.document.pop(key, None)
        return UpdateResult(1)

    async def find_one_and_update(self, query, update, **_kwargs):
        result = await self.update_one(query, update)
        return dict(self.document) if result.matched_count else None


class SetupCollection:
    def __init__(self, document=None):
        self.document = {"_id": "config", **(document or {})}

    async def find_one(self, _query, *_args):
        return dict(self.document)

    async def find_one_and_update(self, _query, update, **_kwargs):
        for field, amount in update.get("$inc", {}).items():
            self.document[field] = int(self.document.get(field, 0)) + amount
        return dict(self.document)

    async def update_one(self, _query, update, **_kwargs):
        self.document.update(update.get("$set", {}))
        for field, value in update.get("$max", {}).items():
            self.document[field] = max(int(self.document.get(field, 0)), int(value))
        return UpdateResult(1)


def test_thread_names_are_stable_and_never_encode_status():
    public, staff = thread_service.thread_names("main", 7, "Shaun Example")
    assert public == "main-7-shaun-example"
    assert staff == "staff-main-7-shaun-example"
    assert "new" not in public
    assert "approved" not in public


def test_create_ticket_owns_acknowledgement_without_dispatcher_state_io():
    action = dispatcher.registered_functions["create_ticket"]
    assert action.opens_modal is True
    assert action.no_return is True
    assert action.preload_state is False


def test_creation_lease_is_global_across_source_guilds():
    assert thread_service._creation_id(10, 30, "main") == "thread:30:main"
    assert thread_service._creation_id(999, 30, "main") == "thread:30:main"


def test_only_owner_can_establish_initial_ticket_target():
    assert handlers._can_configure_thread_target(
        actor_id=handlers.TICKET_BOOTSTRAP_OWNER_ID,
        guild_id=10,
        config={},
    )
    assert not handlers._can_configure_thread_target(
        actor_id=999,
        guild_id=10,
        config={},
    )


def test_bound_target_allows_local_admins_and_rejects_foreign_admins():
    config = {"ticket_target_guild_id": 10}
    assert handlers._can_configure_thread_target(
        actor_id=999,
        guild_id=10,
        config=config,
    )
    assert not handlers._can_configure_thread_target(
        actor_id=999,
        guild_id=11,
        config=config,
    )


def test_ticket_number_allocation_seeds_from_canonical_max_and_is_concurrent_safe():
    class Cursor:
        def __init__(self, documents):
            self.documents = list(documents)

        def sort(self, _spec):
            self.documents.sort(
                key=lambda document: int(document["ticket_number"]), reverse=True
            )
            return self

        def limit(self, amount):
            self.documents = self.documents[:amount]
            return self

        async def to_list(self, length=None):
            return list(self.documents if length is None else self.documents[:length])

    class Tickets:
        def find(self, query, *_args):
            assert query["ticket_type"] == "main"
            return Cursor([
                {"ticket_number": 8},
                {"ticket_number": 50},
                {"ticket_number": 17},
            ])

    mongo = SimpleNamespace(
        tickets=Tickets(),
        ticket_setup=SetupCollection({"main_ticket_counter": 3}),
    )

    async def allocate_pair():
        return await asyncio.gather(
            thread_service.reserve_ticket_number(mongo, "main"),
            thread_service.reserve_ticket_number(mongo, "main"),
        )

    first, second = asyncio.run(allocate_pair())
    assert {first, second} == {51, 52}
    assert mongo.ticket_setup.document["main_ticket_counter"] == 52


def test_thread_configuration_requires_both_parents_and_role():
    with pytest.raises(thread_service.ThreadConfigurationError, match="candidate_parent"):
        thread_service.parents_from_config({"ticket_target_guild_id": 10}, 10, "main")


def test_staff_parent_must_be_distinct():
    parents = thread_service.ThreadParents(10, 20, 20, 30)
    with pytest.raises(thread_service.ThreadConfigurationError, match="different"):
        asyncio.run(thread_service.validate_thread_parents(
            SimpleNamespace(), parents, bot_user_id=40
        ))


def test_recruiter_must_manage_candidate_parent():
    class Rest:
        async def fetch_channel(self, channel_id):
            return SimpleNamespace(
                id=channel_id,
                guild_id=10,
                type=hikari.ChannelType.GUILD_TEXT,
                permission_overwrites={},
            )

        async def fetch_guild(self, _guild_id):
            return SimpleNamespace(owner_id=777)

        async def fetch_member(self, _guild_id, _member_id):
            return SimpleNamespace(id=99, role_ids=(99,))

        async def fetch_roles(self, _guild_id):
            recruiter = (
                hikari.Permissions.VIEW_CHANNEL
                | hikari.Permissions.READ_MESSAGE_HISTORY
                | hikari.Permissions.SEND_MESSAGES_IN_THREADS
            )
            return [
                SimpleNamespace(id=10, permissions=hikari.Permissions.NONE),
                SimpleNamespace(id=99, permissions=hikari.Permissions.ADMINISTRATOR),
                SimpleNamespace(id=40, permissions=recruiter),
            ]

    with pytest.raises(thread_service.ThreadConfigurationError, match="candidate parent"):
        asyncio.run(thread_service.validate_thread_parents(
            Rest(),
            thread_service.ThreadParents(10, 20, 21, 40),
            bot_user_id=99,
        ))


def _valid_parent_rest(
    *,
    mentionable: bool,
    bot_can_mention: bool,
    staff_role_leak: bool = False,
    staff_member_leak: bool = False,
    staff_admin_member: bool = False,
):
    class Rest:
        async def fetch_channel(self, channel_id):
            overwrites = []
            if channel_id == 21:
                if not staff_role_leak:
                    overwrites.append(SimpleNamespace(
                        id=50,
                        type=hikari.PermissionOverwriteType.ROLE,
                        allow=hikari.Permissions.NONE,
                        deny=hikari.Permissions.VIEW_CHANNEL,
                    ))
                if staff_member_leak:
                    overwrites.append(SimpleNamespace(
                        id=60,
                        type=hikari.PermissionOverwriteType.MEMBER,
                        allow=hikari.Permissions.VIEW_CHANNEL,
                        deny=hikari.Permissions.NONE,
                    ))
                if staff_admin_member:
                    overwrites.append(SimpleNamespace(
                        id=61,
                        type=hikari.PermissionOverwriteType.MEMBER,
                        allow=hikari.Permissions.VIEW_CHANNEL,
                        deny=hikari.Permissions.NONE,
                    ))
            return SimpleNamespace(
                id=channel_id,
                guild_id=10,
                type=hikari.ChannelType.GUILD_TEXT,
                permission_overwrites=overwrites,
            )

        async def fetch_guild(self, _guild_id):
            return SimpleNamespace(owner_id=777)

        async def fetch_member(self, _guild_id, member_id):
            role_ids = (
                (99,) if member_id == 99 else
                (70,) if member_id == 61 else
                () if member_id == 60 else
                (50,)
            )
            return SimpleNamespace(id=member_id, role_ids=role_ids)

        async def fetch_roles(self, _guild_id):
            bot_permissions = (
                hikari.Permissions.VIEW_CHANNEL
                | hikari.Permissions.READ_MESSAGE_HISTORY
                | hikari.Permissions.SEND_MESSAGES
                | hikari.Permissions.SEND_MESSAGES_IN_THREADS
                | hikari.Permissions.MANAGE_THREADS
                | hikari.Permissions.CREATE_PRIVATE_THREADS
                | hikari.Permissions.CREATE_PUBLIC_THREADS
                | hikari.Permissions.ATTACH_FILES
            )
            if bot_can_mention:
                bot_permissions |= hikari.Permissions.MENTION_ROLES
            recruiter_permissions = (
                hikari.Permissions.VIEW_CHANNEL
                | hikari.Permissions.READ_MESSAGE_HISTORY
                | hikari.Permissions.SEND_MESSAGES_IN_THREADS
                | hikari.Permissions.MANAGE_THREADS
            )
            return [
                SimpleNamespace(
                    id=10, permissions=hikari.Permissions.NONE, is_managed=False,
                ),
                SimpleNamespace(
                    id=99, permissions=bot_permissions, is_managed=True,
                ),
                SimpleNamespace(
                    id=40,
                    permissions=recruiter_permissions,
                    is_mentionable=mentionable,
                    is_managed=False,
                ),
                SimpleNamespace(
                    id=50,
                    permissions=(
                        hikari.Permissions.VIEW_CHANNEL
                        | hikari.Permissions.READ_MESSAGE_HISTORY
                    ),
                    is_managed=False,
                ),
                SimpleNamespace(
                    id=70,
                    permissions=hikari.Permissions.ADMINISTRATOR,
                    is_managed=False,
                ),
            ]

    return Rest()


@pytest.mark.parametrize(
    ("mentionable", "bot_can_mention"),
    [(True, False), (False, True)],
)
def test_recruiter_notification_has_a_valid_ping_path(mentionable, bot_can_mention):
    asyncio.run(thread_service.validate_thread_parents(
        _valid_parent_rest(
            mentionable=mentionable, bot_can_mention=bot_can_mention
        ),
        thread_service.ThreadParents(10, 20, 21, 40),
        bot_user_id=99,
    ))


def test_recruiter_notification_fails_without_a_ping_path():
    with pytest.raises(thread_service.ThreadConfigurationError, match="mentionable"):
        asyncio.run(thread_service.validate_thread_parents(
            _valid_parent_rest(mentionable=False, bot_can_mention=False),
            thread_service.ThreadParents(10, 20, 21, 40),
            bot_user_id=99,
        ))


def test_staff_parent_rejects_non_recruiter_role_visibility():
    with pytest.raises(thread_service.ThreadConfigurationError, match="non-recruiter role"):
        asyncio.run(thread_service.validate_thread_parents(
            _valid_parent_rest(
                mentionable=True,
                bot_can_mention=False,
                staff_role_leak=True,
            ),
            thread_service.ThreadParents(10, 20, 21, 40),
            bot_user_id=99,
        ))


def test_staff_parent_rejects_unrelated_member_overwrite():
    with pytest.raises(thread_service.ThreadConfigurationError, match="non-recruiter member"):
        asyncio.run(thread_service.validate_thread_parents(
            _valid_parent_rest(
                mentionable=True,
                bot_can_mention=False,
                staff_member_leak=True,
            ),
            thread_service.ThreadParents(10, 20, 21, 40),
            bot_user_id=99,
        ))


def test_staff_parent_preserves_administrator_member_access():
    asyncio.run(thread_service.validate_thread_parents(
        _valid_parent_rest(
            mentionable=True,
            bot_can_mention=False,
            staff_admin_member=True,
        ),
        thread_service.ThreadParents(10, 20, 21, 40),
        bot_user_id=99,
    ))


def test_applicant_must_be_able_to_send_in_candidate_threads():
    with pytest.raises(thread_service.ThreadConfigurationError, match="applicant is missing"):
        asyncio.run(thread_service.validate_thread_parents(
            _valid_parent_rest(mentionable=True, bot_can_mention=False),
            thread_service.ThreadParents(10, 20, 21, 40),
            bot_user_id=99,
            applicant_user_id=30,
        ))


def test_questionnaire_preserves_copy_and_assets():
    main = repr(thread_service._questionnaire_components("main", None))
    fwa = repr(thread_service._questionnaire_components("fwa", None))
    assert "Warriors United Main Clan Entry Ticket" in main
    assert "Your age, time zone, and country" in main
    assert "What are you looking for in a clan?" in main
    assert "A recruiter will reply as soon as possible." in main
    assert "WU_Logo.png" in main
    assert "Warriors United FWA Clan Entry Ticket" in fwa
    assert "LazyCWL and the daily FWA process?" in fwa
    assert "WU_FWA_Ticket.jpg" in fwa


def test_opening_message_mentions_only_candidate_and_recruiter(monkeypatch):
    calls = []

    async def send_once(*_args, **kwargs):
        calls.append((_args, kwargs))

    async def questionnaire_exists(*_args, **_kwargs):
        return True

    monkeypatch.setattr(thread_service, "_send_components_once", send_once)
    monkeypatch.setattr(thread_service, "_questionnaire_exists", questionnaire_exists)
    ticket_doc = _ticket()
    ticket_doc["recruiter_role_id"] = 40
    asyncio.run(thread_service._deliver_opening_messages(SimpleNamespace(), ticket_doc))
    assert calls[0][1]["user_mentions"] == [30]
    assert calls[0][1]["role_mentions"] is False
    assert "<@30>" in repr(calls[0][0][3])
    assert "<@&40>" not in repr(calls[0][0][3])
    assert calls[1][1]["user_mentions"] is False
    assert calls[1][1]["role_mentions"] == [40]
    assert "<@&40>" in repr(calls[1][0][3])
    assert "<@30>" not in repr(calls[1][0][3])


def test_legacy_migration_help_explains_overrides_and_confirmation():
    options = legacy_migration.MigrateLegacyTicket._command_data.options
    assert options["type"].description == (
        "Auto detects the type. Choose Main or FWA only to override the detected value"
    )
    assert "Open/new tickets are refused" in options["status"].description
    assert "Override all player tags" in options["player-tags"].description
    assert "accept listed attachment risks" in options["attachment-ack"].description
    assert options["confirm"].description == (
        "False previews only. True creates or resumes this ticket"
    )
    assert all(len(option.description) <= 100 for option in options.values())


def test_player_tag_capture_is_normalized_and_deduplicated():
    tags = handlers._PLAYER_TAG_RE.findall("#abc123 and #ABC123 then #PYLQ")
    assert sorted({item.upper() for item in tags}) == ["#ABC123", "#PYLQ"]


def test_message_snapshot_includes_attachment_names():
    message = SimpleNamespace(
        content="My answer",
        attachments=[SimpleNamespace(filename="base.png")],
    )
    assert handlers._candidate_message_snapshot(message) == "My answer\nAttachments: base.png"


def test_creation_reuses_naive_expired_lease(monkeypatch):
    collection = CreationStateCollection({
        "_id": "thread:30:main",
        "state": "retry",
        "lease_until": datetime(2026, 8, 20, 5, 0),
        "ticket_number": 4,
        "guild_id": 10,
        "candidate_parent_id": 20,
        "staff_parent_id": 21,
        "recruiter_role_id": 40,
    })
    mongo = SimpleNamespace(ticket_creation_state=collection)
    monkeypatch.setattr(thread_service, "_creation_index_ready", True)
    parents = thread_service.ThreadParents(10, 20, 21, 40)

    owner, state, resumed = asyncio.run(thread_service._claim_creation(
        mongo,
        guild_id=10,
        user_id=30,
        username="Applicant",
        display_name=None,
        ticket_type="main",
        parents=parents,
        now=NOW,
    ))

    assert owner
    assert resumed is True
    assert state["ticket_number"] == 4


def test_creation_rejects_active_lease(monkeypatch):
    collection = CreationStateCollection({
        "_id": "thread:30:main",
        "state": "creating",
        "lease_until": NOW + timedelta(minutes=1),
    })
    mongo = SimpleNamespace(ticket_creation_state=collection)
    monkeypatch.setattr(thread_service, "_creation_index_ready", True)
    with pytest.raises(thread_service.ThreadCreationBusy):
        asyncio.run(thread_service._claim_creation(
            mongo,
            guild_id=10,
            user_id=30,
            username="Applicant",
            display_name=None,
            ticket_type="main",
            parents=thread_service.ThreadParents(10, 20, 21, 40),
            now=NOW,
        ))


def test_bound_creation_refuses_parent_change(monkeypatch):
    collection = CreationStateCollection({
        "_id": "thread:30:main",
        "state": "retry",
        "ticket_number": 4,
        "guild_id": 10,
        "candidate_parent_id": 20,
        "staff_parent_id": 21,
        "recruiter_role_id": 40,
    })
    mongo = SimpleNamespace(ticket_creation_state=collection)
    monkeypatch.setattr(thread_service, "_creation_index_ready", True)
    with pytest.raises(thread_service.ThreadConfigurationError, match="original"):
        asyncio.run(thread_service._claim_creation(
            mongo,
            guild_id=10,
            user_id=30,
            username="Applicant",
            display_name=None,
            ticket_type="main",
            parents=thread_service.ThreadParents(10, 200, 201, 40),
            now=NOW,
        ))


def test_partial_live_pair_is_quarantined_when_cancelled(monkeypatch):
    state = {
        "_id": "thread:30:main",
        "guild_id": 10,
        "user_id": 30,
        "username": "Applicant",
        "ticket_type": "main",
        "candidate_parent_id": 20,
        "staff_parent_id": 21,
        "ticket_number": 1,
        "candidate_name": "main-1-applicant",
        "staff_name": "staff-main-1-applicant",
    }

    class Rest:
        def __init__(self):
            self.edits = []

        async def create_thread(self, *_args, **_kwargs):
            return SimpleNamespace(id=101, is_archived=False, is_locked=False)

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    async def missing(*_args, **_kwargs):
        return None

    async def unchanged(_rest, thread):
        return thread

    async def checkpoint_cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(thread_service, "_fetch_or_recover_thread", missing)
    monkeypatch.setattr(thread_service, "_unarchive_if_needed", unchanged)
    monkeypatch.setattr(thread_service, "_state_update", checkpoint_cancelled)
    rest = Rest()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(thread_service._ensure_live_thread_pair(
            rest=rest,
            mongo=SimpleNamespace(),
            state=state,
            owner="owner",
            bot_user_id=999,
        ))

    assert rest.edits == [(101, {
        "locked": True,
        "archived": True,
        "reason": "Quarantining incomplete ticket creation for safe resume",
    })]


def test_live_creation_cancellation_releases_retry_state(monkeypatch):
    owner = "creation-owner"
    state = {
        "_id": "thread:30:main",
        "lease_owner": owner,
        "lease_until": NOW + timedelta(minutes=1),
        "state": "creating",
        "guild_id": 10,
        "user_id": 30,
        "username": "Applicant",
        "display_name": "Applicant",
        "ticket_type": "main",
        "candidate_parent_id": 20,
        "staff_parent_id": 21,
        "recruiter_role_id": 40,
        "ticket_number": 1,
    }
    creation_state = CreationStateCollection(state)
    mongo = SimpleNamespace(ticket_creation_state=creation_state)

    class Rest:
        def __init__(self):
            self.edits = []

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    async def no_op(*_args, **_kwargs):
        return None

    async def no_existing(*_args, **_kwargs):
        return None

    async def claim(*_args, **_kwargs):
        return owner, dict(state), False

    async def pair(*_args, **_kwargs):
        return SimpleNamespace(id=101), SimpleNamespace(id=102), dict(state)

    async def cancelled_insert(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(thread_service, "ensure_creation_indexes", no_op)
    monkeypatch.setattr(thread_service, "validate_thread_parents", no_op)
    monkeypatch.setattr(thread_service.store, "find_open_for_applicant", no_existing)
    monkeypatch.setattr(thread_service, "_committed_ticket_for_creation_state", no_existing)
    monkeypatch.setattr(thread_service, "_claim_creation", claim)
    monkeypatch.setattr(thread_service, "_ensure_live_thread_pair", pair)
    monkeypatch.setattr(thread_service.store, "insert_one", cancelled_insert)
    rest = Rest()
    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=99), rest=rest)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(thread_service.create_live_thread_ticket(
            bot=bot,
            mongo=mongo,
            guild_id=10,
            user_id=30,
            username="Applicant",
            display_name="Applicant",
            ticket_type="main",
            config={
                "ticket_target_guild_id": 10,
                "main_candidate_parent": 20,
                "main_staff_parent": 21,
                "main_recruiter_role": 40,
            },
        ))

    assert [channel_id for channel_id, _kwargs in rest.edits] == [101, 102]
    assert all(
        kwargs["locked"] is True and kwargs["archived"] is True
        for _channel_id, kwargs in rest.edits
    )
    assert creation_state.document["state"] == "retry"
    assert creation_state.document["last_error"] == "CancelledError"
    assert "lease_owner" not in creation_state.document
    assert "lease_until" not in creation_state.document


def test_post_commit_account_sync_failure_resumes_without_duplicate_pair(monkeypatch):
    owner = "creation-owner"
    creation_state = CreationStateCollection()
    automation_states = AutomationStateCollection()
    mongo = SimpleNamespace(
        ticket_creation_state=creation_state,
        ticket_automation_state=automation_states,
    )
    committed = {"doc": None}
    calls = {"claim": 0, "pair": 0, "insert": 0, "sync": 0}

    class Rest:
        def __init__(self):
            self.edits = []

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    async def no_op(*_args, **_kwargs):
        return None

    async def find_open(*_args, **_kwargs):
        return dict(committed["doc"]) if committed["doc"] else None

    async def no_bound(*_args, **_kwargs):
        return None

    async def claim(*_args, **_kwargs):
        calls["claim"] += 1
        state = {
            "_id": "thread:30:main",
            "lease_owner": owner,
            "state": "creating",
            "guild_id": 10,
            "user_id": 30,
            "username": "Applicant",
            "display_name": "Applicant",
            "ticket_type": "main",
            "candidate_parent_id": 20,
            "staff_parent_id": 21,
            "recruiter_role_id": 40,
            "ticket_number": 1,
        }
        creation_state.document = dict(state)
        return owner, state, False

    async def pair(*_args, **kwargs):
        calls["pair"] += 1
        return SimpleNamespace(id=101), SimpleNamespace(id=102), kwargs["state"]

    async def insert(_mongo, document):
        calls["insert"] += 1
        committed["doc"] = dict(document)
        return dict(document)

    async def sync(_mongo, _client, ticket_id, *, source, **_kwargs):
        calls["sync"] += 1
        assert ticket_id == "ticket_101"
        if calls["sync"] == 1:
            raise account_sync.AccountSyncError("interrupted after commit")
        updated = dict(committed["doc"])
        updated["linked_accounts"] = {
            "version": 1,
            "state": account_sync.STATE_READY,
            "current": [{
                "tag": "#ABC123",
                "name": "Applicant",
                "town_hall": 17,
                "profile_status": "loaded",
            }],
            "current_tags": ["#ABC123"],
            "retry_required": False,
            "source": source,
            "revision": 1,
        }
        committed["doc"] = updated
        return account_sync.AccountSyncResult(
            updated,
            account_sync.snapshot_from_ticket(updated),
            added_tags=("#ABC123",),
        )

    monkeypatch.setattr(thread_service, "ensure_creation_indexes", no_op)
    monkeypatch.setattr(thread_service, "validate_thread_parents", no_op)
    monkeypatch.setattr(thread_service.store, "find_open_for_applicant", find_open)
    monkeypatch.setattr(thread_service, "_committed_ticket_for_creation_state", no_bound)
    monkeypatch.setattr(thread_service, "_claim_creation", claim)
    monkeypatch.setattr(thread_service, "_ensure_live_thread_pair", pair)
    monkeypatch.setattr(thread_service.store, "insert_one", insert)
    monkeypatch.setattr(thread_service.account_sync, "sync_ticket_accounts", sync)
    monkeypatch.setattr(thread_service, "_deliver_opening_messages", no_op)
    monkeypatch.setattr(thread_service, "reconcile_ticket_pair", no_op)
    monkeypatch.setattr(thread_service, "notify_console_after_change", no_op)
    rest = Rest()
    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=99), rest=rest)
    config = {
        "ticket_target_guild_id": 10,
        "main_candidate_parent": 20,
        "main_staff_parent": 21,
        "main_recruiter_role": 40,
    }

    with pytest.raises(account_sync.AccountSyncError):
        asyncio.run(thread_service.create_live_thread_ticket(
            bot=bot,
            mongo=mongo,
            guild_id=10,
            user_id=30,
            username="Applicant",
            display_name="Applicant",
            ticket_type="main",
            config=config,
            coc_client=object(),
        ))
    resumed = asyncio.run(thread_service.create_live_thread_ticket(
        bot=bot,
        mongo=mongo,
        guild_id=10,
        user_id=30,
        username="Applicant",
        display_name="Applicant",
        ticket_type="main",
        config=config,
        coc_client=object(),
    ))

    assert resumed.resumed is True
    assert resumed.ticket["linked_accounts"]["current_tags"] == ["#ABC123"]
    assert calls == {"claim": 1, "pair": 1, "insert": 1, "sync": 2}
    assert rest.edits == []
    assert creation_state.document["state"] == "complete"


def test_foreign_guild_click_is_rejected_before_global_ticket_lookup(monkeypatch):
    called = False

    async def find_open(*_args, **_kwargs):
        nonlocal called
        called = True
        return _ticket()

    monkeypatch.setattr(thread_service, "_creation_index_ready", True)
    monkeypatch.setattr(thread_service.store, "find_open_for_applicant", find_open)
    with pytest.raises(thread_service.ThreadConfigurationError, match="different guild"):
        asyncio.run(thread_service.create_live_thread_ticket(
            bot=SimpleNamespace(),
            mongo=SimpleNamespace(),
            guild_id=11,
            user_id=30,
            username="Applicant",
            display_name=None,
            ticket_type="main",
            config={
                "ticket_target_guild_id": 10,
                "main_candidate_parent": 20,
                "main_staff_parent": 21,
                "main_recruiter_role": 40,
            },
        ))
    assert called is False


def test_committed_ticket_heals_completion_then_terminal_user_gets_fresh_attempt(monkeypatch):
    state_collection = CreationStateCollection()
    state_collection.fail_complete_once = True
    automation_states = AutomationStateCollection()
    mongo = SimpleNamespace(
        ticket_creation_state=state_collection,
        ticket_setup=SetupCollection({"main_ticket_counter": 0}),
        ticket_automation_state=automation_states,
    )
    committed = {"doc": None}
    monkeypatch.setattr(thread_service, "_creation_index_ready", True)
    claims = []
    pairs = [
        (SimpleNamespace(id=101), SimpleNamespace(id=102), 1),
        (SimpleNamespace(id=201), SimpleNamespace(id=202), 2),
    ]

    async def no_validate(*_args, **_kwargs):
        return None, None

    async def find_open(_mongo, *, user_id, ticket_type):
        doc = committed["doc"]
        return dict(doc) if doc and doc["status"] == "open" else None

    async def claim(_mongo, **kwargs):
        index = len(claims)
        claims.append(kwargs)
        candidate, staff, number = pairs[index]
        owner = f"owner-{number}"
        doc = {
            "_id": "thread:30:main",
            "lease_owner": owner,
            "state": "creating",
            "guild_id": 10,
            "user_id": 30,
            "username": "Applicant",
            "display_name": "Applicant",
            "ticket_type": "main",
            "candidate_parent_id": 20,
            "staff_parent_id": 21,
            "recruiter_role_id": 40,
            "ticket_number": number,
        }
        state_collection.document = dict(doc)
        return owner, doc, index > 0

    async def pair(*, state, **_kwargs):
        index = len(claims) - 1
        candidate, staff, number = pairs[index]
        state = {**state, "ticket_number": number}
        return candidate, staff, state

    async def insert(_mongo, document):
        committed["doc"] = dict(document)
        return dict(document)

    async def by_location(_mongo, location):
        doc = committed["doc"]
        return dict(doc) if doc and doc["location"]["id"] == location else None

    async def committed_for_state(*_args, **_kwargs):
        doc = committed["doc"]
        return dict(doc) if doc else None

    async def no_messages(*_args, **_kwargs):
        return None

    monkeypatch.setattr(thread_service, "validate_thread_parents", no_validate)
    monkeypatch.setattr(thread_service.store, "find_open_for_applicant", find_open)
    monkeypatch.setattr(thread_service, "_claim_creation", claim)
    monkeypatch.setattr(thread_service, "_ensure_live_thread_pair", pair)
    monkeypatch.setattr(thread_service.store, "insert_one", insert)
    monkeypatch.setattr(thread_service.store, "find_by_location", by_location)
    monkeypatch.setattr(
        thread_service, "_committed_ticket_for_creation_state", committed_for_state
    )
    monkeypatch.setattr(thread_service, "_deliver_opening_messages", no_messages)
    monkeypatch.setattr(thread_service, "reconcile_ticket_pair", no_messages)
    monkeypatch.setattr(thread_service, "notify_console_after_change", no_messages)
    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=99), rest=SimpleNamespace())
    config = {
        "ticket_target_guild_id": 10,
        "main_candidate_parent": 20,
        "main_staff_parent": 21,
        "main_recruiter_role": 40,
    }

    first = asyncio.run(thread_service.create_live_thread_ticket(
        bot=bot,
        mongo=mongo,
        guild_id=10,
        user_id=30,
        username="Applicant",
        display_name=None,
        ticket_type="main",
        config=config,
    ))
    assert first.ticket["location"]["id"] == 101
    assert first.delivery_pending is True
    assert committed["doc"]["location"]["id"] == 101

    recovered = asyncio.run(thread_service.create_live_thread_ticket(
        bot=bot,
        mongo=mongo,
        guild_id=10,
        user_id=30,
        username="Applicant",
        display_name=None,
        ticket_type="main",
        config=config,
    ))
    assert recovered.ticket["location"]["id"] == 101
    assert state_collection.document["state"] == "complete"
    assert len(claims) == 1

    committed["doc"]["status"] = "denied"
    later = asyncio.run(thread_service.create_live_thread_ticket(
        bot=bot,
        mongo=mongo,
        guild_id=10,
        user_id=30,
        username="Applicant",
        display_name=None,
        ticket_type="main",
        config=config,
    ))
    assert later.ticket["location"]["id"] == 201
    assert later.ticket["ticket_number"] == 2
    assert len(claims) == 2
    for ticket_id, staff_id in (("ticket_101", 102), ("ticket_201", 202)):
        context = automation_states.documents[f"ticket_staff_context:{ticket_id}"]
        assert context["ticket_id"] == ticket_id
        assert context["staff_space_id"] == staff_id
        assert context["delivery_state"] == "pending"


def test_live_creation_queue_failure_resumes_without_duplicate_resources(monkeypatch):
    creation_states = CreationStateCollection()
    automation_states = AutomationStateCollection(fail_updates=1)
    mongo = SimpleNamespace(
        ticket_creation_state=creation_states,
        ticket_automation_state=automation_states,
    )
    committed = {"doc": None}
    calls = {"claim": 0, "pair": 0, "insert": 0, "opening": 0}
    messages = set()

    async def no_validate(*_args, **_kwargs):
        return None, None

    async def find_open(_mongo, *, user_id, ticket_type):
        document = committed["doc"]
        return dict(document) if document and document["status"] == "open" else None

    async def no_bound_ticket(*_args, **_kwargs):
        return None

    async def claim(_mongo, **_kwargs):
        calls["claim"] += 1
        state = {
            "_id": "thread:30:main",
            "lease_owner": "owner",
            "state": "creating",
            "guild_id": 10,
            "user_id": 30,
            "username": "Applicant",
            "display_name": "Applicant",
            "ticket_type": "main",
            "candidate_parent_id": 20,
            "staff_parent_id": 21,
            "recruiter_role_id": 40,
            "ticket_number": 1,
        }
        creation_states.document = dict(state)
        return "owner", state, False

    async def pair(*, state, **_kwargs):
        calls["pair"] += 1
        return SimpleNamespace(id=101), SimpleNamespace(id=102), state

    async def insert(_mongo, document):
        calls["insert"] += 1
        committed["doc"] = dict(document)
        return dict(document)

    async def opening_messages(_rest, ticket):
        calls["opening"] += 1
        messages.update({
            f"ticket-setup:{ticket['location']['id']}:candidate",
            f"ticket-setup:{ticket['location']['id']}:staff",
        })

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(thread_service, "_creation_index_ready", True)
    monkeypatch.setattr(thread_service, "validate_thread_parents", no_validate)
    monkeypatch.setattr(thread_service.store, "find_open_for_applicant", find_open)
    monkeypatch.setattr(
        thread_service, "_committed_ticket_for_creation_state", no_bound_ticket
    )
    monkeypatch.setattr(thread_service, "_claim_creation", claim)
    monkeypatch.setattr(thread_service, "_ensure_live_thread_pair", pair)
    monkeypatch.setattr(thread_service.store, "insert_one", insert)
    monkeypatch.setattr(thread_service, "_deliver_opening_messages", opening_messages)
    monkeypatch.setattr(thread_service, "reconcile_ticket_pair", no_op)
    monkeypatch.setattr(thread_service, "notify_console_after_change", no_op)
    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=99), rest=SimpleNamespace())
    config = {
        "ticket_target_guild_id": 10,
        "main_candidate_parent": 20,
        "main_staff_parent": 21,
        "main_recruiter_role": 40,
    }

    first = asyncio.run(thread_service.create_live_thread_ticket(
        bot=bot,
        mongo=mongo,
        guild_id=10,
        user_id=30,
        username="Applicant",
        display_name="Applicant",
        ticket_type="main",
        config=config,
    ))
    assert first.delivery_pending is True
    assert creation_states.document["state"] == "delivery_pending"
    assert automation_states.documents == {}

    resumed = asyncio.run(thread_service.create_live_thread_ticket(
        bot=bot,
        mongo=mongo,
        guild_id=10,
        user_id=30,
        username="Applicant",
        display_name="Applicant",
        ticket_type="main",
        config=config,
    ))
    assert resumed.ticket["_id"] == first.ticket["_id"] == "ticket_101"
    assert resumed.resumed is True
    assert resumed.delivery_pending is False
    assert calls == {"claim": 1, "pair": 1, "insert": 1, "opening": 2}
    assert messages == {
        "ticket-setup:101:candidate",
        "ticket-setup:101:staff",
    }
    assert creation_states.document["state"] == "complete"
    context = automation_states.documents["ticket_staff_context:ticket_101"]
    assert context["ticket_id"] == "ticket_101"
    assert context["staff_space_id"] == 102
    assert context["delivery_state"] == "pending"


def test_archive_pair_is_idempotent():
    class Rest:
        def __init__(self):
            self.edits = []

        async def fetch_channel(self, channel_id):
            if channel_id == 101:
                return SimpleNamespace(id=101, is_archived=True, is_locked=True)
            return SimpleNamespace(id=102, is_archived=False, is_locked=False)

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    rest = Rest()
    asyncio.run(thread_service.archive_ticket_pair(rest, _ticket(status="denied", source={
        "guild_id": 1, "channel_id": 2,
    })))
    assert [item[0] for item in rest.edits] == [102]
    assert rest.edits[0][1]["locked"] is True
    assert rest.edits[0][1]["archived"] is True


def test_reconcile_open_unarchives_and_unlocks_both():
    class Rest:
        def __init__(self):
            self.edits = []

        async def fetch_channel(self, channel_id):
            return SimpleNamespace(id=channel_id, is_archived=True, is_locked=True)

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    rest = Rest()
    asyncio.run(thread_service.reconcile_ticket_pair(rest, _ticket()))
    assert {item[0] for item in rest.edits} == {101, 102}
    assert all(item[1]["archived"] is False for item in rest.edits)
    assert all(item[1]["locked"] is False for item in rest.edits)


@pytest.mark.parametrize(("source_ticket", "channel_name"), [
    ({"status": "open"}, "main-9-applicant"),
    ({"status": "new"}, "main-9-applicant"),
    (None, "new-main-9-applicant"),
    (None, "🆕main-9-applicant"),
])
def test_legacy_status_refuses_open_even_with_terminal_override(
    source_ticket,
    channel_name,
):
    with pytest.raises(legacy_migration.LegacyTicketStillOpen):
        legacy_migration._infer_status(source_ticket, channel_name, "denied")


@pytest.mark.parametrize(("stored", "selected"), [
    ("approved", "denied"),
    ("denied", "approved"),
])
def test_explicit_terminal_status_corrects_stored_terminal(stored, selected):
    assert legacy_migration._infer_status(
        {"status": stored}, "main-9-applicant", selected
    ) == selected


@pytest.mark.parametrize(("stored", "selected"), [
    ("main", "fwa"),
    ("fwa", "main"),
])
def test_explicit_ticket_type_corrects_stored_type(stored, selected):
    assert legacy_migration._infer_ticket_type(
        {"ticket_type": stored}, "ticket-9-applicant", selected
    ) == selected


def test_explicit_metadata_corrections_beat_channel_inference():
    assert legacy_migration._infer_status(
        None, "✅main-9-applicant", "denied"
    ) == "denied"
    assert legacy_migration._infer_ticket_type(
        None, "approved-main-9-applicant", "fwa"
    ) == "fwa"


def test_stored_terminal_status_beats_stale_channel_prefix():
    assert legacy_migration._infer_status(
        {"status": "approved"}, "🆕main-9-applicant", None
    ) == "approved"


def test_stored_closed_status_requires_explicit_outcome():
    with pytest.raises(legacy_migration.LegacyMigrationError, match="explicit"):
        legacy_migration._infer_status(
            {"status": "closed"}, "✅main-9-applicant", None
        )
    assert legacy_migration._infer_status(
        {"status": "closed"}, "✅main-9-applicant", "denied"
    ) == "denied"
    assert legacy_migration._infer_status(
        {"status": "closed"}, "🆕main-9-applicant", "approved"
    ) == "approved"


@pytest.mark.parametrize(("candidate_parent_id", "staff_parent_id"), [
    (99, 21),
    (20, 99),
    (99, 98),
])
def test_legacy_migration_rejects_any_unconfigured_parent_pair(
    candidate_parent_id,
    staff_parent_id,
):
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1,
        source_channel_id=2,
        target_guild_id=10,
        candidate_parent_id=candidate_parent_id,
        staff_parent_id=staff_parent_id,
    )
    config = {
        "main_candidate_parent": 20,
        "main_staff_parent": 21,
        "main_recruiter_role": 40,
    }
    with pytest.raises(legacy_migration.LegacyMigrationError, match="configured MAIN"):
        legacy_migration._configured_destination(config, request, "main")


def test_legacy_migration_accepts_only_the_configured_parent_pair():
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1,
        source_channel_id=2,
        target_guild_id=10,
        candidate_parent_id=20,
        staff_parent_id=21,
    )
    parents = legacy_migration._configured_destination({
        "main_candidate_parent": 20,
        "main_staff_parent": 21,
        "main_recruiter_role": 40,
    }, request, "main")
    assert (parents.candidate_parent_id, parents.staff_parent_id) == (20, 21)


def test_parent_autocomplete_offers_only_configured_channels(monkeypatch):
    class Rest:
        def __init__(self):
            self.fetched = []

        async def fetch_channel(self, channel_id):
            self.fetched.append(channel_id)
            return SimpleNamespace(
                id=channel_id,
                guild_id=10,
                type=hikari.ChannelType.GUILD_TEXT,
                name=f"parent-{channel_id}",
            )

    class Context:
        def __init__(self, rest):
            self.interaction = SimpleNamespace(
                guild_id=10,
                user=SimpleNamespace(id=77),
                member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR),
            )
            self.client = SimpleNamespace(app=SimpleNamespace(rest=rest))
            self.focused = SimpleNamespace(value="")
            self.response = None

        def get_option(self, name):
            assert name == "target-guild"
            return SimpleNamespace(value="10")

        async def respond(self, choices):
            self.response = choices

    async def administrator(*_args, **_kwargs):
        return True

    monkeypatch.setattr(legacy_migration, "_guild_administrator", administrator)
    rest = Rest()
    ctx = Context(rest)
    mongo = SimpleNamespace(ticket_setup=SetupCollection({
        "ticket_target_guild_id": 10,
        "main_candidate_parent": 20,
        "fwa_candidate_parent": 22,
        "main_staff_parent": 21,
        "fwa_staff_parent": 23,
    }))
    asyncio.run(legacy_migration._configured_parent_choices(
        ctx, mongo, field="candidate_parent"
    ))
    assert rest.fetched == [20, 22]
    assert {value for _label, value in ctx.response} == {"20", "22"}


def test_mention_clone_is_plain_and_non_pingable():
    message = SimpleNamespace(
        user_mentions={55: SimpleNamespace(display_name="Old User", username="old")}
    )
    content = legacy_migration._plain_mentions(
        "<@55> <@&66> <#77> @everyone @here",
        message,
        {66: "Recruiters"},
        {77: "tickets"},
    )
    assert content == "@Old User @Recruiters #tickets @\u200beveryone @\u200bhere"
    assert "<@" not in content


def test_long_clone_parts_fit_and_have_unique_durable_markers():
    parts = legacy_migration._message_parts(
        content="x" * 5000,
        source_guild_id=1,
        source_channel_id=2,
        source_message_id=3,
        timestamp=NOW,
    )
    assert len(parts) >= 3
    assert all(len(content) <= 2000 for _marker, content in parts)
    assert len({marker for marker, _content in parts}) == len(parts)
    assert all(marker in content for marker, content in parts)


def test_lost_webhook_response_is_reconciled_without_duplicate():
    marker = "migration-source:1:2:3:1/1"

    class Rest:
        def __init__(self):
            self.executions = 0
            self.scans = 0
            self.kwargs = []

        def fetch_messages(self, _thread_id):
            rest = self

            class Iterator:
                def limit(self, _amount):
                    return self

                async def to_list(self):
                    rest.scans += 1
                    if rest.scans == 1:
                        return []
                    return [SimpleNamespace(content=f"copied\n-# {marker}")]

            return Iterator()

        async def execute_webhook(self, *_args, **_kwargs):
            self.executions += 1
            self.kwargs.append(_kwargs)
            raise TimeoutError("response lost after commit")

    rest = Rest()
    message = SimpleNamespace(
        author=SimpleNamespace(display_name="A", username="a", display_avatar_url=None),
        attachments=[],
        embeds=[],
    )
    losses = asyncio.run(legacy_migration._execute_clone_part(
        rest=rest,
        webhook=SimpleNamespace(id=8, token="secret"),
        thread_id=9,
        marker=marker,
        content=f"hello\n-# {marker}",
        message=message,
        include_payload=True,
    ))
    assert losses == []
    assert rest.executions == 1
    assert rest.kwargs[0]["mentions_everyone"] is False
    assert rest.kwargs[0]["user_mentions"] is False
    assert rest.kwargs[0]["role_mentions"] is False
    assert rest.kwargs[0]["flags"] == hikari.MessageFlag.SUPPRESS_NOTIFICATIONS
    assert "avatar_url" not in rest.kwargs[0]


def test_public_and_staff_histories_resume_from_confirmed_checkpoints(monkeypatch):
    messages = {
        2: [
            SimpleNamespace(
                id=10, content="already copied", timestamp=NOW, user_mentions={}
            ),
            SimpleNamespace(id=11, content="candidate", timestamp=NOW, user_mentions={}),
        ],
        3: [SimpleNamespace(id=20, content="staff", timestamp=NOW, user_mentions={})],
    }
    copied = []
    state = {
        "_id": "legacy:1:2",
        "source": {"guild_id": 1},
        "progress": {
            "public": {"last_source_message_id": 10, "copied": 1, "losses": []},
            "staff": {"last_source_message_id": None, "copied": 0, "losses": []},
        },
    }

    async def all_messages(_rest, channel_id):
        return messages[channel_id]

    async def clone_part(**kwargs):
        copied.append((kwargs["thread_id"], kwargs["marker"]))
        return []

    async def update(_mongo, _migration_id, _owner, fields):
        for path, value in fields.items():
            cursor = state
            parts = path.split(".")
            for part in parts[:-1]:
                cursor = cursor.setdefault(part, {})
            cursor[parts[-1]] = value
        return state

    async def no_markers(_rest, _thread_id):
        return set()

    monkeypatch.setattr(legacy_migration, "_all_messages", all_messages)
    monkeypatch.setattr(legacy_migration, "_execute_clone_part", clone_part)
    monkeypatch.setattr(legacy_migration, "_migration_update", update)
    monkeypatch.setattr(legacy_migration, "_destination_markers", no_markers)

    async def run_copy():
        await legacy_migration._copy_space(
            bot=SimpleNamespace(rest=SimpleNamespace()),
            mongo=SimpleNamespace(),
            state=state,
            owner="owner",
            space="public",
            source_channel_id=2,
            destination_thread_id=101,
            webhook=SimpleNamespace(),
            role_names={},
            channel_names={},
        )
        await legacy_migration._copy_space(
            bot=SimpleNamespace(rest=SimpleNamespace()),
            mongo=SimpleNamespace(),
            state=state,
            owner="owner",
            space="staff",
            source_channel_id=3,
            destination_thread_id=102,
            webhook=SimpleNamespace(),
            role_names={},
            channel_names={},
        )

    asyncio.run(run_copy())
    assert copied == [
        (101, "migration-source:1:2:11:1/1"),
        (102, "migration-source:1:3:20:1/1"),
    ]
    assert state["progress"]["public"]["last_source_message_id"] == 11
    assert state["progress"]["staff"]["last_source_message_id"] == 20


def test_attachment_fallback_retains_idempotency_marker():
    marker = "migration-source:1:2:3:1/1"

    class Rest:
        def __init__(self):
            self.payloads = []

        def fetch_messages(self, _thread_id):
            class Iterator:
                def limit(self, _amount):
                    return self

                async def to_list(self):
                    return []

            return Iterator()

        async def execute_webhook(self, *_args, **kwargs):
            content = _args[2]
            self.payloads.append(content)
            if kwargs.get("attachments"):
                raise FileNotFoundError("attachment URL unavailable")

    rest = Rest()
    message = SimpleNamespace(
        author=SimpleNamespace(display_name="A", username="a", display_avatar_url=None),
        attachments=[SimpleNamespace(filename="proof.png")],
        embeds=[],
    )
    known_markers = set()
    losses = asyncio.run(legacy_migration._execute_clone_part(
        rest=rest,
        webhook=SimpleNamespace(id=8, token="secret"),
        thread_id=9,
        marker=marker,
        content=("x" * 1950) + f"\n-# {marker}",
        message=message,
        include_payload=True,
        allow_payload_loss=True,
        known_markers=known_markers,
    ))
    assert losses == ["proof.png"]
    assert marker in rest.payloads[-1]
    assert len(rest.payloads[-1]) <= 2000
    assert asyncio.run(legacy_migration._execute_clone_part(
        rest=rest,
        webhook=SimpleNamespace(id=8, token="secret"),
        thread_id=9,
        marker=marker,
        content=("x" * 1950) + f"\n-# {marker}",
        message=message,
        include_payload=True,
        allow_payload_loss=True,
        known_markers=known_markers,
    )) == []
    assert len(rest.payloads) == 2


def test_attachment_fallback_bounds_long_filenames_without_losing_marker_or_audit():
    marker = "migration-source:1:2:3:1/1"
    filenames = [f"proof-{index}-" + "x" * 900 + ".png" for index in range(10)]

    class Rest:
        def __init__(self):
            self.payloads = []

        async def execute_webhook(self, *_args, **kwargs):
            self.payloads.append(_args[2])
            if kwargs.get("attachments"):
                raise FileNotFoundError("attachment URL unavailable")

        def fetch_messages(self, _thread_id):
            return EmptyLazyIterator()

    rest = Rest()
    message = SimpleNamespace(
        author=SimpleNamespace(display_name="A", username="a", display_avatar_url=None),
        attachments=[SimpleNamespace(filename=name) for name in filenames],
        embeds=[],
    )
    losses = asyncio.run(legacy_migration._execute_clone_part(
        rest=rest,
        webhook=SimpleNamespace(id=8, token="secret"),
        thread_id=9,
        marker=marker,
        content=("x" * 1950) + f"\n-# {marker}",
        message=message,
        include_payload=True,
        allow_payload_loss=True,
    ))

    fallback = rest.payloads[-1]
    assert len(fallback) <= legacy_migration.DISCORD_MESSAGE_CONTENT_LIMIT
    assert fallback.endswith(f"\n-# {marker}")
    assert filenames[0] in fallback
    assert filenames[1] in fallback
    assert filenames[2] not in fallback
    assert "+8 filenames omitted" in fallback
    assert losses == filenames


def test_unaccepted_runtime_payload_loss_stops_without_fallback():
    marker = "migration-source:1:2:3:1/1"

    class Rest:
        def __init__(self):
            self.payloads = []

        def fetch_messages(self, _thread_id):
            return EmptyLazyIterator()

        async def execute_webhook(self, *_args, **kwargs):
            self.payloads.append(_args[2])
            if kwargs.get("attachments"):
                raise FileNotFoundError("attachment URL unavailable")

    rest = Rest()
    message = SimpleNamespace(
        author=SimpleNamespace(display_name="A", username="a", display_avatar_url=None),
        attachments=[SimpleNamespace(filename="proof.png")],
        embeds=[],
    )
    with pytest.raises(legacy_migration.LegacyMigrationError, match="source message remains pending"):
        asyncio.run(legacy_migration._execute_clone_part(
            rest=rest,
            webhook=SimpleNamespace(id=8, token="secret"),
            thread_id=9,
            marker=marker,
            content=f"proof\n-# {marker}",
            message=message,
            include_payload=True,
            allow_payload_loss=False,
        ))
    assert len(rest.payloads) == 1


def test_unaccepted_runtime_loss_does_not_advance_source_checkpoint(monkeypatch):
    state = {
        "_id": "legacy:1:2",
        "source": {"guild_id": 1},
        "progress": {
            "public": {"last_source_message_id": None, "copied": 0, "losses": []},
        },
        "attachment_policy": {"accepted": False},
    }
    message = SimpleNamespace(
        id=9,
        timestamp=NOW,
        content="proof",
        user_mentions={},
        attachments=[SimpleNamespace(filename="proof.png")],
        embeds=[],
    )
    updates = []

    async def messages(_rest, _channel_id):
        return [message]

    async def markers(_rest, _thread_id):
        return set()

    async def refuses_loss(**kwargs):
        assert kwargs["allow_payload_loss"] is False
        raise legacy_migration.LegacyMigrationError("checkpoint remains pending")

    async def update(*args, **kwargs):
        updates.append((args, kwargs))
        return state

    monkeypatch.setattr(legacy_migration, "_all_messages", messages)
    monkeypatch.setattr(legacy_migration, "_destination_markers", markers)
    monkeypatch.setattr(legacy_migration, "_execute_clone_part", refuses_loss)
    monkeypatch.setattr(legacy_migration, "_migration_update", update)
    with pytest.raises(legacy_migration.LegacyMigrationError, match="checkpoint"):
        asyncio.run(legacy_migration._copy_space(
            bot=SimpleNamespace(rest=SimpleNamespace()),
            mongo=SimpleNamespace(),
            state=state,
            owner="owner",
            space="public",
            source_channel_id=2,
            destination_thread_id=101,
            webhook=SimpleNamespace(id=8, token="secret"),
            role_names={},
            channel_names={},
        ))
    assert updates == []
    assert state["progress"]["public"]["last_source_message_id"] is None


@pytest.mark.parametrize("failure", [
    TimeoutError("timeout"),
    ConnectionError("connection reset"),
])
def test_transient_failure_never_becomes_accepted_payload_loss(failure):
    class Rest:
        def fetch_messages(self, _thread_id):
            return EmptyLazyIterator()

        async def execute_webhook(self, *_args, **_kwargs):
            raise failure

    message = SimpleNamespace(
        author=SimpleNamespace(display_name="A", username="a", display_avatar_url=None),
        attachments=[SimpleNamespace(filename="proof.png")],
        embeds=[],
    )
    with pytest.raises(type(failure)):
        asyncio.run(legacy_migration._execute_clone_part(
            rest=Rest(),
            webhook=SimpleNamespace(id=8, token="secret"),
            thread_id=9,
            marker="migration-source:1:2:3:1/1",
            content="proof\n-# migration-source:1:2:3:1/1",
            message=message,
            include_payload=True,
            allow_payload_loss=True,
        ))


def test_legacy_player_tag_override_replaces_all_inference():
    source_ticket = {
        "player_tags": ["not a valid stored tag"],
        "player_tag": "#OLD",
    }
    messages = [
        SimpleNamespace(
            author=SimpleNamespace(id=30),
            content="Applicant supplied #FOUND before the correction.",
        ),
    ]

    assert legacy_migration._player_tags(
        source_ticket,
        messages,
        (" fixed ",),
        applicant_user_id=30,
    ) == ("#FIXED",)


def test_legacy_player_tag_inference_uses_stored_fields_and_applicant_messages_only():
    source_ticket = {
        "player_tags": "#stored",
        "player_tag": "abc",
        "tag": "#XYZ",
    }
    messages = [
        SimpleNamespace(author=SimpleNamespace(id=30), content="Mine is #app123."),
        SimpleNamespace(author=SimpleNamespace(id=40), content="Staff tag #STAFF."),
        SimpleNamespace(author=SimpleNamespace(id=31), content="Visitor tag #THIRD."),
    ]

    assert legacy_migration._player_tags(
        source_ticket,
        messages,
        ("", "  "),
        applicant_user_id=30,
    ) == ("#STORED", "#ABC", "#XYZ", "#APP123")


class MigrationCollection:
    def __init__(self, docs=None):
        self.docs = {doc["_id"]: dict(doc) for doc in (docs or [])}

    async def create_index(self, *_args, **kwargs):
        return kwargs.get("name")

    async def find_one(self, query):
        return self.docs.get(query.get("_id"))

    async def count_documents(self, query):
        return sum(
            1 for doc in self.docs.values()
            if all(doc.get(key) == value for key, value in query.items())
        )

    async def insert_one(self, doc):
        if doc["_id"] in self.docs:
            raise legacy_migration.DuplicateKeyError("duplicate")
        self.docs[doc["_id"]] = dict(doc)


def _preview(request=None):
    request = request or legacy_migration.LegacyMigrationRequest(
        source_guild_id=1,
        source_channel_id=2,
        target_guild_id=10,
        candidate_parent_id=20,
        staff_parent_id=21,
    )
    return legacy_migration.LegacyMigrationPreview(
        request=request,
        source_channel=SimpleNamespace(id=2, name="approved-main-8-applicant"),
        source_staff_thread=SimpleNamespace(id=3),
        source_ticket=None,
        ticket_type="main",
        status="approved",
        user_id=30,
        username="Applicant",
        display_name="Applicant",
        player_tags=("#ABC",),
        created_at=NOW,
        original_ticket_number=8,
        public_message_count=5,
        staff_message_count=2,
        attachment_count=0,
        recruiter_role_id=40,
    )


def test_explicit_metadata_corrections_reach_preview_and_durable_state(monkeypatch):
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1,
        source_channel_id=2,
        target_guild_id=10,
        candidate_parent_id=20,
        staff_parent_id=21,
        ticket_type_override="fwa",
        status_override="denied",
    )
    source_ticket = {"ticket_type": "main", "status": "approved"}
    preview = replace(
        _preview(request),
        source_ticket=source_ticket,
        ticket_type=legacy_migration._infer_ticket_type(
            source_ticket, "approved-main-8-applicant", request.ticket_type_override
        ),
        status=legacy_migration._infer_status(
            source_ticket, "approved-main-8-applicant", request.status_override
        ),
    )
    assert (preview.ticket_type, preview.status) == ("fwa", "denied")

    mongo = SimpleNamespace(
        ticket_migrations=MigrationCollection(),
        ticket_setup=SetupCollection({
            "ticket_target_guild_id": 10,
            "legacy_migration_pilot_approved": True,
        }),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)
    _owner, state, resumed = asyncio.run(
        legacy_migration._claim_migration(mongo, preview)
    )
    assert resumed is False
    assert state["metadata"]["ticket_type"] == "fwa"
    assert state["metadata"]["status"] == "denied"


def _attachment_preview(status="live", *, request=None, message_id=9):
    return replace(
        _preview(request),
        attachment_count=1,
        attachment_audit=(legacy_migration.AttachmentAuditResult(
            source_channel_id=2,
            source_message_id=message_id,
            filename="proof.png",
            status=status,
        ),),
    )


def test_safe_attachment_preview_needs_no_loss_acknowledgment():
    assert legacy_migration._require_attachment_ack(
        _attachment_preview("live")
    ) is None


def test_risky_attachment_preview_requires_exact_bound_acknowledgment():
    preview = _attachment_preview("unknown")
    token = legacy_migration._attachment_ack_token(preview)
    assert token and token.startswith("LOSS-")
    with pytest.raises(legacy_migration.LegacyMigrationError, match="accept every"):
        legacy_migration._require_attachment_ack(preview)

    accepted = replace(
        preview,
        request=replace(preview.request, attachment_ack=token),
    )
    assert legacy_migration._require_attachment_ack(accepted) == token

    changed = replace(accepted, user_id=31)
    with pytest.raises(legacy_migration.LegacyMigrationError, match="does not match"):
        legacy_migration._require_attachment_ack(changed)


def test_risky_attachment_claim_refuses_before_any_mongo_access():
    with pytest.raises(legacy_migration.LegacyMigrationError, match="accept every"):
        asyncio.run(legacy_migration._claim_migration(
            SimpleNamespace(), _attachment_preview("unknown")
        ))


def test_attachment_ack_token_survives_live_to_unrecoverable_status_change():
    live = _attachment_preview("live")
    dead = _attachment_preview("unrecoverable")
    assert legacy_migration._attachment_ack_token(live) == (
        legacy_migration._attachment_ack_token(dead)
    )


def test_loss_acceptance_escalates_same_migration_and_audits_actor(monkeypatch):
    class ClaimableCollection(MigrationCollection):
        async def find_one_and_update(self, query, update, **_kwargs):
            document = self.docs.get(query["_id"])
            if document is None:
                return None
            document.update(update.get("$set", {}))
            return dict(document)

    collection = ClaimableCollection()
    mongo = SimpleNamespace(
        ticket_migrations=collection,
        ticket_setup=SetupCollection({
            "ticket_target_guild_id": 10,
            "legacy_migration_pilot_approved": True,
        }),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)
    preview = _attachment_preview("live")
    _owner, created, resumed = asyncio.run(
        legacy_migration._claim_migration(mongo, preview)
    )
    assert resumed is False
    assert created["attachment_policy"]["accepted"] is False

    durable = collection.docs[created["_id"]]
    durable["state"] = "retry"
    durable["lease_until"] = NOW - timedelta(minutes=1)
    durable["progress"]["public"]["last_source_message_id"] = 55
    token = legacy_migration._attachment_ack_token(preview)
    accepted = replace(preview, request=replace(
        preview.request,
        attachment_ack=token,
        attachment_ack_actor_id=77,
        attachment_ack_actor_name="Operator",
    ))
    _owner, escalated, resumed = asyncio.run(
        legacy_migration._claim_migration(mongo, accepted)
    )
    assert resumed is True
    assert escalated["_id"] == created["_id"]
    assert escalated["progress"]["public"]["last_source_message_id"] == 55
    policy = escalated["attachment_policy"]
    assert policy["accepted"] is True
    assert policy["accepted_by"] == 77
    assert policy["accepted_by_name"] == "Operator"
    assert policy["acceptance_audit"][-1]["token"] == token

    collection.docs[created["_id"]]["lease_until"] = NOW - timedelta(minutes=1)
    _owner, preserved, resumed = asyncio.run(
        legacy_migration._claim_migration(mongo, preview)
    )
    assert resumed is True
    assert preserved["attachment_policy"]["accepted"] is True


def test_accepted_policy_rejects_changed_attachment_manifest_without_new_ack():
    original = _attachment_preview("unknown")
    token = legacy_migration._attachment_ack_token(original)
    accepted = replace(original, request=replace(original.request, attachment_ack=token))
    current = {
        "attachment_policy": legacy_migration._attachment_policy_for_claim(
            accepted, None, NOW
        )
    }
    changed = _attachment_preview("live", message_id=10)
    with pytest.raises(legacy_migration.LegacyMigrationError, match="attachments changed"):
        legacy_migration._attachment_policy_for_claim(changed, current, NOW)


def test_runtime_loss_acceptance_is_limited_to_previewed_attachments():
    preview = _attachment_preview("unknown", message_id=9)
    token = legacy_migration._attachment_ack_token(preview)
    accepted = replace(preview, request=replace(preview.request, attachment_ack=token))
    state = {
        "attachment_policy": legacy_migration._attachment_policy_for_claim(
            accepted, None, NOW
        )
    }
    covered = SimpleNamespace(
        id=9,
        attachments=[SimpleNamespace(filename="proof.png")],
    )
    added_later = SimpleNamespace(
        id=10,
        attachments=[SimpleNamespace(filename="proof.png")],
    )
    renamed = SimpleNamespace(
        id=9,
        attachments=[SimpleNamespace(filename="different.png")],
    )
    assert legacy_migration._message_payload_loss_is_accepted(state, 2, covered)
    assert not legacy_migration._message_payload_loss_is_accepted(state, 2, added_later)
    assert not legacy_migration._message_payload_loss_is_accepted(state, 2, renamed)


def test_pilot_hard_stops_after_five_completed(monkeypatch):
    docs = [
        {"_id": f"legacy:{index}:1", "kind": "legacy_thread_migration", "state": "complete"}
        for index in range(5)
    ]
    mongo = SimpleNamespace(
        ticket_migrations=MigrationCollection(docs),
        ticket_setup=SetupCollection({
            "ticket_target_guild_id": 10,
            "legacy_migration_pilot_approved": False,
        }),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", False)

    async def indexes_ready(_mongo):
        return []

    monkeypatch.setattr(
        legacy_migration.thread_service, "ensure_canonical_ticket_store", indexes_ready
    )
    with pytest.raises(legacy_migration.PilotLimitReached):
        asyncio.run(legacy_migration._claim_migration(mongo, _preview()))


def test_pilot_allows_the_fifth_confirmed_ticket(monkeypatch):
    docs = [
        {"_id": f"legacy:{index}:1", "kind": "legacy_thread_migration", "state": "complete"}
        for index in range(4)
    ]
    collection = MigrationCollection(docs)
    mongo = SimpleNamespace(
        ticket_migrations=collection,
        ticket_setup=SetupCollection({
            "ticket_target_guild_id": 10,
            "legacy_migration_pilot_approved": False,
        }),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", False)

    async def indexes_ready(_mongo):
        return []

    monkeypatch.setattr(
        legacy_migration.thread_service, "ensure_canonical_ticket_store", indexes_ready
    )
    _owner, state, resumed = asyncio.run(
        legacy_migration._claim_migration(mongo, _preview())
    )
    assert resumed is False
    assert state["state"] == "creating"
    assert "legacy:1:2" in collection.docs


def test_atomic_pilot_reservation_refuses_a_concurrent_sixth(monkeypatch):
    docs = [
        {"_id": f"legacy:{index}:1", "kind": "legacy_thread_migration", "state": "complete"}
        for index in range(4)
    ]

    class CappedSetup(SetupCollection):
        def __init__(self):
            super().__init__({
                "ticket_target_guild_id": 10,
                "legacy_migration_pilot_approved": False,
                "legacy_migration_pilot_slots_reserved": 5,
            })

        async def update_one(self, _query, update, **_kwargs):
            maximum = update.get("$max", {}).get(
                "legacy_migration_pilot_slots_reserved", 0
            )
            self.document["legacy_migration_pilot_slots_reserved"] = max(
                self.document["legacy_migration_pilot_slots_reserved"], maximum
            )
            return UpdateResult(1)

        async def find_one_and_update(self, _query, update, **_kwargs):
            if update.get("$inc", {}).get("legacy_migration_pilot_slots_reserved"):
                return None
            return await super().find_one_and_update(_query, update, **_kwargs)

    mongo = SimpleNamespace(
        ticket_migrations=MigrationCollection(docs),
        ticket_setup=CappedSetup(),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)
    with pytest.raises(legacy_migration.PilotLimitReached):
        asyncio.run(legacy_migration._claim_migration(mongo, _preview()))


def test_partial_migration_pair_is_archived_for_safe_resume(monkeypatch):
    state = {
        "_id": "legacy:1:2",
        "metadata": {"ticket_type": "main", "username": "Applicant"},
        "destination": {
            "guild_id": 10,
            "candidate_parent_id": 20,
            "staff_parent_id": 21,
            "ticket_number": 9,
            "public_name": "main-9-applicant",
            "staff_name": "staff-main-9-applicant",
        },
    }

    class Rest:
        def __init__(self):
            self.edits = []

        async def create_thread(self, *_args, **_kwargs):
            return SimpleNamespace(id=101, is_archived=False)

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    async def missing(*_args, **_kwargs):
        return None

    async def unchanged(_rest, thread):
        return thread

    async def update_fails(*_args, **_kwargs):
        raise TimeoutError("checkpoint acknowledgement lost")

    monkeypatch.setattr(thread_service, "_fetch_or_recover_thread", missing)
    monkeypatch.setattr(thread_service, "_unarchive_if_needed", unchanged)
    monkeypatch.setattr(legacy_migration, "_migration_update", update_fails)
    rest = Rest()
    with pytest.raises(TimeoutError):
        asyncio.run(legacy_migration._ensure_destination_pair(
            SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=999)),
            SimpleNamespace(),
            state,
            "owner",
        ))
    assert rest.edits == [(101, {
        "locked": True,
        "archived": True,
        "reason": "Quarantining interrupted legacy migration for resume",
    })]


def test_partial_migration_pair_is_quarantined_when_cancelled(monkeypatch):
    state = {
        "_id": "legacy:1:2",
        "metadata": {"ticket_type": "main", "username": "Applicant"},
        "destination": {
            "guild_id": 10,
            "candidate_parent_id": 20,
            "staff_parent_id": 21,
            "ticket_number": 9,
            "public_name": "main-9-applicant",
            "staff_name": "staff-main-9-applicant",
        },
    }

    class Rest:
        def __init__(self):
            self.edits = []

        async def create_thread(self, *_args, **_kwargs):
            return SimpleNamespace(id=101, is_archived=False)

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    async def missing(*_args, **_kwargs):
        return None

    async def unchanged(_rest, thread):
        return thread

    async def checkpoint_cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(thread_service, "_fetch_or_recover_thread", missing)
    monkeypatch.setattr(thread_service, "_unarchive_if_needed", unchanged)
    monkeypatch.setattr(legacy_migration, "_migration_update", checkpoint_cancelled)
    rest = Rest()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(legacy_migration._ensure_destination_pair(
            SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=999)),
            SimpleNamespace(),
            state,
            "owner",
        ))

    assert rest.edits == [(101, {
        "locked": True,
        "archived": True,
        "reason": "Quarantining interrupted legacy migration for resume",
    })]


def test_migration_cancellation_cleans_destinations_and_releases_retry(monkeypatch):
    owner = "migration-owner"
    state = {
        "_id": "legacy:1:2",
        "lease_owner": owner,
        "lease_until": NOW + timedelta(minutes=1),
        "state": "copying",
        "source": {
            "guild_id": 1,
            "channel_id": 2,
            "staff_thread_id": 3,
            "channel_name": "approved-main-8-applicant",
            "ticket_number": 8,
        },
        "destination": {
            "guild_id": 10,
            "candidate_parent_id": 20,
            "staff_parent_id": 21,
            "ticket_number": 9,
            "public_name": "main-9-applicant",
            "staff_name": "staff-main-9-applicant",
            "public_thread_id": 101,
            "staff_thread_id": 102,
        },
        "metadata": {
            "ticket_type": "main",
            "status": "approved",
            "user_id": 30,
            "username": "Applicant",
            "display_name": "Applicant",
            "player_tags": ["#ABC"],
            "created_at": NOW,
        },
        "webhooks": {"public_id": 401, "staff_id": 402},
    }

    class Collection:
        def __init__(self, document):
            self.document = dict(document)

        async def update_one(self, query, update):
            assert query == {"_id": state["_id"], "lease_owner": owner}
            self.document.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                self.document.pop(key, None)
            return UpdateResult(1)

    class Rest:
        def __init__(self):
            self.deleted_webhooks = []
            self.edits = []

        async def fetch_roles(self, guild_id):
            assert guild_id == 1
            return []

        async def fetch_guild_channels(self, guild_id):
            assert guild_id == 1
            return []

        async def delete_webhook(self, webhook_id, **_kwargs):
            self.deleted_webhooks.append(webhook_id)

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    async def claim(*_args, **_kwargs):
        return owner, dict(state), False

    async def pair(*_args, **_kwargs):
        return SimpleNamespace(id=101), SimpleNamespace(id=102), dict(state)

    async def webhook(_rest, _parent_id, _migration_id, space):
        return SimpleNamespace(id=401 if space == "public" else 402, token="token")

    async def unchanged(_mongo, _migration_id, _owner, _fields):
        return dict(state)

    async def copy_cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    collection = Collection(state)
    mongo = SimpleNamespace(ticket_migrations=collection)
    rest = Rest()
    bot = SimpleNamespace(rest=rest)
    monkeypatch.setattr(legacy_migration, "_claim_migration", claim)
    monkeypatch.setattr(legacy_migration, "_ensure_destination_pair", pair)
    monkeypatch.setattr(legacy_migration, "_temporary_webhook", webhook)
    monkeypatch.setattr(legacy_migration, "_migration_update", unchanged)
    monkeypatch.setattr(legacy_migration, "_copy_space", copy_cancelled)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(legacy_migration.migrate_legacy_ticket(
            bot=bot,
            mongo=mongo,
            preview=_preview(),
        ))

    assert sorted(rest.deleted_webhooks) == [401, 402]
    assert [channel_id for channel_id, _kwargs in rest.edits] == [101, 102]
    assert all(
        kwargs["locked"] is True and kwargs["archived"] is True
        for _channel_id, kwargs in rest.edits
    )
    assert collection.document["state"] == "retry"
    assert collection.document["last_error"] == "CancelledError"
    assert "lease_owner" not in collection.document
    assert "lease_until" not in collection.document
    assert "webhooks" not in collection.document


def test_locked_archived_thread_is_sequentially_reopened_and_unlocked():
    class Rest:
        def __init__(self):
            self.edits = []

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))
            return SimpleNamespace(
                id=channel_id,
                is_archived=False,
                is_locked=kwargs.get("locked", True),
            )

    rest = Rest()
    thread = SimpleNamespace(id=101, is_archived=True, is_locked=True)
    asyncio.run(thread_service._unarchive_if_needed(rest, thread))
    assert rest.edits[0][1] == {
        "archived": False,
        "reason": "Resuming ticket creation",
    }
    assert rest.edits[1][1] == {
        "locked": False,
        "reason": "Resuming ticket creation",
    }


@pytest.mark.parametrize(("field", "value", "message"), [
    ("guild_id", 99, "wrong guild"),
    ("type", hikari.ChannelType.GUILD_PUBLIC_THREAD, "wrong thread type"),
    ("name", "other-ticket", "wrong name"),
    ("owner_id", 998, "wrong owner"),
])
def test_stored_thread_recovery_rejects_identity_mismatch(field, value, message):
    identity = {
        "id": 101,
        "guild_id": 10,
        "parent_id": 20,
        "name": "main-1-applicant",
        "type": hikari.ChannelType.GUILD_PRIVATE_THREAD,
        "owner_id": 999,
    }
    identity[field] = value

    class Rest:
        async def fetch_channel(self, _thread_id):
            return SimpleNamespace(**identity)

    with pytest.raises(thread_service.ThreadTicketError, match=message):
        asyncio.run(thread_service._fetch_or_recover_thread(
            Rest(),
            thread_id=101,
            guild_id=10,
            parent_id=20,
            name="main-1-applicant",
            private=True,
            expected_owner_id=999,
        ))


def test_named_thread_recovery_rejects_wrong_thread_type():
    class EmptyArchived:
        async def to_list(self):
            return []

    class Rest:
        async def fetch_active_threads(self, _guild_id):
            return [SimpleNamespace(
                id=101,
                guild_id=10,
                parent_id=20,
                name="main-1-applicant",
                type=hikari.ChannelType.GUILD_PUBLIC_THREAD,
                owner_id=999,
            )]

        def fetch_private_archived_threads(self, _parent_id):
            return EmptyArchived()

    with pytest.raises(thread_service.ThreadTicketError, match="wrong thread type"):
        asyncio.run(thread_service._find_named_thread(
            Rest(),
            guild_id=10,
            parent_id=20,
            name="main-1-applicant",
            private=True,
            expected_owner_id=999,
        ))


def test_resumed_auto_detected_staff_thread_does_not_conflict(monkeypatch):
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1,
        source_channel_id=2,
        target_guild_id=10,
        candidate_parent_id=20,
        staff_parent_id=21,
        source_staff_thread_id=None,
    )
    current = {
        "_id": "legacy:1:2",
        "kind": "legacy_thread_migration",
        "state": "retry",
        "source": {
            "guild_id": 1,
            "channel_id": 2,
            "staff_thread_id": 3,
            "channel_name": "approved-main-8-applicant",
            "ticket_number": 8,
        },
        "destination": {"guild_id": 10, "candidate_parent_id": 20, "staff_parent_id": 21},
        "metadata": {
            "ticket_type": "main",
            "status": "approved",
            "user_id": 30,
            "username": "Applicant",
            "display_name": "Applicant",
            "player_tags": ["#ABC"],
            "created_at": NOW.replace(tzinfo=None),
            "source_ticket_id": None,
            "source_ticket_rev": 0,
        },
        "lease_until": NOW - timedelta(minutes=1),
    }

    class Collection(MigrationCollection):
        async def find_one_and_update(self, query, update, **_kwargs):
            doc = self.docs[query["_id"]]
            doc.update(update["$set"])
            return dict(doc)

    mongo = SimpleNamespace(
        ticket_migrations=Collection([current]),
        ticket_setup=SetupCollection(),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)
    _owner, state, resumed = asyncio.run(
        legacy_migration._claim_migration(mongo, _preview(request))
    )
    assert resumed is True
    assert state["source"]["staff_thread_id"] == 3


@pytest.mark.parametrize(("field", "value"), [
    ("ticket_type", "fwa"),
    ("status", "denied"),
    ("user_id", 31),
    ("player_tags", ("#DIFFERENT",)),
])
def test_migration_resume_rejects_changed_applicant_identity(monkeypatch, field, value):
    collection = MigrationCollection()
    mongo = SimpleNamespace(
        ticket_migrations=collection,
        ticket_setup=SetupCollection({
            "ticket_target_guild_id": 10,
            "legacy_migration_pilot_approved": True,
        }),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)
    preview = _preview()
    asyncio.run(legacy_migration._claim_migration(mongo, preview))
    collection.docs["legacy:1:2"]["state"] = "complete"

    with pytest.raises(legacy_migration.LegacyMigrationError, match="different source"):
        asyncio.run(legacy_migration._claim_migration(
            mongo, replace(preview, **{field: value})
        ))


def test_completed_terminal_migration_reentry_repairs_bound_context_without_delivery(
    monkeypatch,
):
    ticket = _ticket(
        status="approved",
        source={"guild_id": 1, "channel_id": 2},
    )
    state = {
        "_id": "legacy:1:2",
        "kind": "legacy_thread_migration",
        "state": "complete",
        "ticket_id": ticket["_id"],
    }
    states = AutomationStateCollection(fail_updates=1)
    state_id = f"ticket_staff_context:{ticket['_id']}"
    states.documents[state_id] = {
        "_id": state_id,
        "kind": "ticket_staff_context",
        "ticket_id": ticket["_id"],
        "staff_space_id": 999,
        "delivery_state": "delivered",
    }
    mongo = SimpleNamespace(ticket_automation_state=states)
    claims = []

    async def completed_claim(_mongo, preview):
        claims.append(preview.request.source_channel_id)
        return "unused-owner", dict(state), True

    async def find_ticket(_mongo, query):
        assert query == {"_id": ticket["_id"]}
        return dict(ticket)

    async def no_delivery(*_args, **_kwargs):
        raise AssertionError("completed reentry must only bind durable context work")

    monkeypatch.setattr(legacy_migration, "_claim_migration", completed_claim)
    monkeypatch.setattr(legacy_migration.store, "find_one", find_ticket)
    monkeypatch.setattr(
        thread_service, "notify_console_after_change", no_delivery
    )

    with pytest.raises(TimeoutError, match="staff context queue unavailable"):
        asyncio.run(legacy_migration.migrate_legacy_ticket(
            bot=SimpleNamespace(rest=SimpleNamespace()),
            mongo=mongo,
            preview=_preview(),
        ))
    assert state["state"] == "complete"
    assert states.documents[state_id]["staff_space_id"] == 999

    result = asyncio.run(legacy_migration.migrate_legacy_ticket(
        bot=SimpleNamespace(rest=SimpleNamespace()),
        mongo=mongo,
        preview=_preview(),
    ))
    assert claims == [2, 2]
    assert result.resumed is True
    assert result.migration["state"] == "complete"
    context = states.documents[state_id]
    assert context["ticket_id"] == ticket["_id"]
    assert context["staff_space_id"] == ticket["location"]["staff_space_id"]
    assert context["delivery_state"] == "pending"


def test_post_replacement_crash_resumes_same_record_and_completes(monkeypatch):
    original = {
        "_id": "legacy_ticket",
        "type": "ticket",
        "venue": "channel",
        "status": "approved",
        "ticket_type": "main",
        "ticket_number": 42,
        "user_id": 30,
        "username": "Applicant",
        "display_name": "Applicant",
        "player_tags": ["#ABC"],
        "created_at": NOW,
        "rev": 0,
    }
    first_preview = replace(
        _preview(),
        source_ticket=original,
        source_channel=SimpleNamespace(id=2, name="approved-main-42-applicant"),
        original_ticket_number=42,
    )

    class Collection(MigrationCollection):
        async def find_one_and_update(self, query, update, **_kwargs):
            doc = self.docs.get(query["_id"])
            if doc is None:
                return None
            if query.get("lease_owner") and doc.get("lease_owner") != query["lease_owner"]:
                return None
            doc.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                doc.pop(key, None)
            return dict(doc)

    collection = Collection()
    automation_states = AutomationStateCollection()
    mongo = SimpleNamespace(
        ticket_migrations=collection,
        ticket_automation_state=automation_states,
        ticket_setup=SetupCollection({
            "ticket_target_guild_id": 10,
            "legacy_migration_pilot_approved": True,
        }),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)
    asyncio.run(legacy_migration._claim_migration(mongo, first_preview))
    migration = collection.docs["legacy:1:2"]
    migration["state"] = "retry"
    migration["lease_until"] = NOW - timedelta(minutes=1)
    migration["destination"].update({
        "ticket_number": 362,
        "public_name": "main-362-applicant",
        "staff_name": "staff-main-362-applicant",
        "public_thread_id": 101,
        "staff_thread_id": 102,
    })

    source = {
        "guild_id": 1,
        "channel_id": 2,
        "staff_thread_id": 3,
        "channel_name": "approved-main-42-applicant",
        "ticket_number": 42,
    }
    replaced = schema.new_ticket_document(
        ticket_type="main",
        ticket_number=362,
        guild_id=10,
        public_thread_id=101,
        public_parent_id=20,
        staff_thread_id=102,
        staff_parent_id=21,
        user_id=30,
        username="Applicant",
        player_tags=("#ABC",),
        created_at=NOW,
        status="approved",
        source=source,
    )
    replaced["_id"] = "legacy_ticket"
    replaced["rev"] = 1
    replaced["audit"].append({
        "event": "legacy_location_replaced",
        "rev_before": 0,
        "rev_after": 1,
        "to": {"venue": "thread", "location": replaced["location"]},
    })
    resumed_preview = replace(
        first_preview,
        source_ticket=replaced,
        original_ticket_number=legacy_migration._original_ticket_number(
            replaced, first_preview.source_channel.name
        ),
    )
    assert resumed_preview.original_ticket_number == 42
    assert replaced["ticket_number"] == 362

    async def pair(_bot, _mongo, state, _owner):
        return SimpleNamespace(id=101), SimpleNamespace(id=102), state

    async def webhook(_rest, _parent, _migration_id, space):
        return SimpleNamespace(id=1 if space == "public" else 2, token="token")

    async def unchanged(*_args, state, **_kwargs):
        return state

    async def no_op(*_args, **_kwargs):
        return None

    async def already_replaced(_mongo, ticket_id, _canonical, *, expected_rev):
        assert ticket_id == "legacy_ticket"
        assert expected_rev == 1
        return store.Transition(store.WON, replaced, "already migrated")

    monkeypatch.setattr(legacy_migration, "_ensure_destination_pair", pair)
    monkeypatch.setattr(legacy_migration, "_temporary_webhook", webhook)
    monkeypatch.setattr(legacy_migration, "_copy_space", unchanged)
    monkeypatch.setattr(legacy_migration, "_delete_webhook_safely", no_op)
    monkeypatch.setattr(legacy_migration.store, "replace_legacy_location", already_replaced)
    monkeypatch.setattr(thread_service, "notify_console_after_change", no_op)
    monkeypatch.setattr(thread_service, "archive_ticket_pair", no_op)

    class Rest:
        async def fetch_roles(self, _guild_id):
            return []

        async def fetch_guild_channels(self, _guild_id):
            return []

    result = asyncio.run(legacy_migration.migrate_legacy_ticket(
        bot=SimpleNamespace(rest=Rest()), mongo=mongo, preview=resumed_preview
    ))
    assert result.ticket["_id"] == "legacy_ticket"
    assert result.ticket["ticket_number"] == 362
    assert result.migration["source"]["ticket_number"] == 42
    assert result.migration["destination"]["ticket_number"] == 362
    assert result.migration["state"] == "complete"
    assert result.migration["metadata"]["source_ticket_rev"] == 0
    context = automation_states.documents["ticket_staff_context:legacy_ticket"]
    assert context["ticket_id"] == "legacy_ticket"
    assert context["staff_space_id"] == 102
    assert context["delivery_state"] == "pending"

    unrelated_drift = dict(replaced)
    unrelated_drift["rev"] = 2
    with pytest.raises(legacy_migration.LegacyMigrationError, match="different source"):
        asyncio.run(legacy_migration._claim_migration(
            mongo, replace(resumed_preview, source_ticket=unrelated_drift)
        ))


def test_post_insert_crash_resumes_same_new_record_and_completes(monkeypatch):
    first_preview = replace(
        _preview(),
        source_channel=SimpleNamespace(id=2, name="approved-main-42-applicant"),
        original_ticket_number=42,
    )

    class Collection(MigrationCollection):
        async def find_one_and_update(self, query, update, **_kwargs):
            doc = self.docs.get(query["_id"])
            if doc is None:
                return None
            if query.get("lease_owner") and doc.get("lease_owner") != query["lease_owner"]:
                return None
            doc.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                doc.pop(key, None)
            return dict(doc)

        async def update_one(self, query, update, **_kwargs):
            doc = self.docs.get(query["_id"])
            if doc is None:
                return UpdateResult(0)
            if query.get("lease_owner") and doc.get("lease_owner") != query["lease_owner"]:
                return UpdateResult(0)
            doc.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                doc.pop(key, None)
            return UpdateResult(1)

    collection = Collection()
    automation_states = AutomationStateCollection(fail_updates=1)
    mongo = SimpleNamespace(
        ticket_migrations=collection,
        ticket_automation_state=automation_states,
        ticket_setup=SetupCollection({
            "ticket_target_guild_id": 10,
            "legacy_migration_pilot_approved": True,
        }),
    )
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)
    asyncio.run(legacy_migration._claim_migration(mongo, first_preview))
    migration = collection.docs["legacy:1:2"]
    assert migration["metadata"]["source_ticket_id"] is None
    migration["state"] = "retry"
    migration["lease_until"] = NOW - timedelta(minutes=1)
    migration["destination"].update({
        "ticket_number": 362,
        "public_name": "main-362-applicant",
        "staff_name": "staff-main-362-applicant",
        "public_thread_id": 101,
        "staff_thread_id": 102,
    })

    source = {
        "guild_id": 1,
        "channel_id": 2,
        "staff_thread_id": 3,
        "channel_name": "approved-main-42-applicant",
        "ticket_number": 42,
    }
    inserted = schema.new_ticket_document(
        ticket_type="main",
        ticket_number=362,
        guild_id=10,
        public_thread_id=101,
        public_parent_id=20,
        staff_thread_id=102,
        staff_parent_id=21,
        user_id=30,
        username="Applicant",
        display_name="Applicant",
        player_tags=("#ABC",),
        created_at=NOW,
        status="approved",
        source=source,
    )
    assert inserted["_id"] == "ticket_101"
    resumed_preview = replace(
        first_preview,
        source_ticket=inserted,
        original_ticket_number=legacy_migration._original_ticket_number(
            inserted, first_preview.source_channel.name
        ),
    )
    assert resumed_preview.original_ticket_number == 42
    assert inserted["ticket_number"] == 362

    pair_calls = []

    async def pair(_bot, _mongo, state, _owner):
        pair_calls.append((101, 102))
        return SimpleNamespace(id=101), SimpleNamespace(id=102), state

    async def webhook(_rest, _parent, _migration_id, space):
        return SimpleNamespace(id=1 if space == "public" else 2, token="token")

    async def unchanged(*_args, state, **_kwargs):
        return state

    async def no_op(*_args, **_kwargs):
        return None

    replacements = []

    async def already_inserted(_mongo, ticket_id, _canonical, *, expected_rev):
        replacements.append((ticket_id, expected_rev))
        assert ticket_id == "ticket_101"
        assert expected_rev == 0
        return store.Transition(store.WON, inserted, "already migrated")

    monkeypatch.setattr(legacy_migration, "_ensure_destination_pair", pair)
    monkeypatch.setattr(legacy_migration, "_temporary_webhook", webhook)
    monkeypatch.setattr(legacy_migration, "_copy_space", unchanged)
    monkeypatch.setattr(legacy_migration, "_delete_webhook_safely", no_op)
    monkeypatch.setattr(legacy_migration.store, "replace_legacy_location", already_inserted)
    monkeypatch.setattr(thread_service, "notify_console_after_change", no_op)
    monkeypatch.setattr(thread_service, "archive_ticket_pair", no_op)

    class Rest:
        def __init__(self):
            self.archived = []

        async def fetch_roles(self, _guild_id):
            return []

        async def fetch_guild_channels(self, _guild_id):
            return []

        async def edit_channel(self, channel_id, **kwargs):
            self.archived.append((channel_id, kwargs))

    rest = Rest()
    bot = SimpleNamespace(rest=rest)
    with pytest.raises(TimeoutError, match="staff context queue unavailable"):
        asyncio.run(legacy_migration.migrate_legacy_ticket(
            bot=bot, mongo=mongo, preview=resumed_preview
        ))
    assert collection.docs["legacy:1:2"]["state"] == "retry"
    assert automation_states.documents == {}
    assert [channel_id for channel_id, _kwargs in rest.archived] == [101, 102]

    result = asyncio.run(legacy_migration.migrate_legacy_ticket(
        bot=bot, mongo=mongo, preview=resumed_preview
    ))
    assert replacements == [("ticket_101", 0), ("ticket_101", 0)]
    assert pair_calls == [(101, 102), (101, 102)]
    assert result.ticket["_id"] == "ticket_101"
    assert result.ticket["ticket_number"] == 362
    assert result.migration["source"]["ticket_number"] == 42
    assert result.migration["destination"]["ticket_number"] == 362
    assert result.migration["metadata"]["source_ticket_id"] is None
    assert result.migration["state"] == "complete"
    context = automation_states.documents["ticket_staff_context:ticket_101"]
    assert context["ticket_id"] == "ticket_101"
    assert context["staff_space_id"] == 102
    assert context["delivery_state"] == "pending"

    unrelated = dict(inserted)
    unrelated["audit"] = []
    with pytest.raises(legacy_migration.LegacyMigrationError, match="different source"):
        asyncio.run(legacy_migration._claim_migration(
            mongo, replace(resumed_preview, source_ticket=unrelated)
        ))


def test_migration_thread_names_use_new_unique_target_number():
    public, staff = legacy_migration._migration_thread_names("fwa", 99, "Applicant")
    assert public == "fwa-99-applicant"
    assert staff == "staff-fwa-99-applicant"


def test_opening_delivery_scans_beyond_last_hundred_messages():
    marker = "ticket-setup:101:candidate"
    questionnaire = "Warriors United Main Clan Entry Ticket"

    class Cursor:
        def limit(self, _amount):
            raise AssertionError("delivery reconciliation must not truncate history")

        async def to_list(self):
            old_marker = SimpleNamespace(content=f"-# {marker}", components=[])
            old_questionnaire = SimpleNamespace(
                content="",
                components=[SimpleNamespace(
                    content=questionnaire,
                    components=[],
                )],
            )
            newer = [SimpleNamespace(content="chat", components=[]) for _ in range(150)]
            return [old_marker, old_questionnaire, *newer]

    class Rest:
        def __init__(self):
            self.created = 0

        def fetch_messages(self, _channel_id):
            return Cursor()

        async def create_message(self, *_args, **_kwargs):
            self.created += 1

    rest = Rest()
    asyncio.run(thread_service._send_once(rest, 101, marker, "welcome"))
    assert asyncio.run(
        thread_service._questionnaire_exists(rest, 101, "main")
    ) is True
    assert rest.created == 0


def test_destination_marker_scan_is_not_limited_to_recent_messages():
    marker = "migration-source:1:2:3:1/1"

    class Cursor:
        def limit(self, _amount):
            raise AssertionError("migration marker scan must inspect full history")

        async def to_list(self):
            return [SimpleNamespace(content=marker)] + [
                SimpleNamespace(content="newer") for _ in range(150)
            ]

    rest = SimpleNamespace(fetch_messages=lambda _thread_id: Cursor())
    assert asyncio.run(
        legacy_migration._destination_has_marker(rest, 101, marker)
    ) is True


def test_console_hub_refresh_runs_even_when_staff_context_fails(monkeypatch):
    from extensions.commands.tickets import console

    calls = []

    async def context_fails(*_args, **_kwargs):
        raise RuntimeError("context unavailable")

    async def hub_refresh(*_args, **_kwargs):
        calls.append("hub")
        return True

    monkeypatch.setattr(console, "deliver_staff_identity_context", context_fails)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", hub_refresh)
    asyncio.run(thread_service.notify_console_after_change(
        SimpleNamespace(), SimpleNamespace(), {"_id": "ticket_101"}, reason="test"
    ))
    assert calls == ["hub"]


def test_attachment_audit_is_bounded_and_reports_unknown(monkeypatch):
    monkeypatch.setattr(legacy_migration, "ATTACHMENT_AUDIT_LIMIT", 1)
    message = SimpleNamespace(
        id=9,
        attachments=[
            SimpleNamespace(filename="missing.png", url=None),
            SimpleNamespace(filename="later.png", url="https://invalid.example"),
        ],
    )
    audit = asyncio.run(legacy_migration._audit_attachment_urls(((2, [message]),)))
    assert [item.status for item in audit] == ["unknown", "not_audited"]
    preview = replace(_preview(), attachment_count=2, attachment_audit=audit)
    summary = legacy_migration._attachment_audit_summary(preview)
    assert "unknown or not checked `2`" in summary


def test_legacy_summary_bounds_many_tags_without_changing_preview_metadata():
    tags = tuple(f"#TAG{index:06d}" for index in range(1000))
    preview = replace(
        _attachment_preview("unrecoverable"),
        player_tags=tags,
    )

    summary = legacy_migration._migration_summary(preview)
    dry_run = (
        "🔎 **DRY RUN — nothing was written.**\n"
        + summary
        + "\nRe-run with `confirm: true` to create or resume this one ticket."
    )
    completed = (
        "✅ **Legacy ticket migrated and archived.**\n"
        + summary
        + "\n**Candidate:** <#123456789012345678> • "
        "**Staff:** <#223456789012345678>\n"
        "Source channels and messages were not modified."
    )

    assert len(summary) <= legacy_migration.MIGRATION_SUMMARY_LIMIT
    assert len(dry_run) <= legacy_migration.DISCORD_MESSAGE_CONTENT_LIMIT
    assert len(completed) <= legacy_migration.DISCORD_MESSAGE_CONTENT_LIMIT
    assert "tags omitted" in summary
    assert "LOSS-" in summary
    assert preview.player_tags == tags


def test_canonical_store_guard_blocks_legacy_primary(monkeypatch):
    async def legacy_store(_mongo):
        return store.STORE_BUTTON

    monkeypatch.setattr(thread_service.store, "active_store", legacy_store)
    with pytest.raises(thread_service.ThreadConfigurationError, match="migrate-store"):
        asyncio.run(thread_service.ensure_canonical_ticket_store(SimpleNamespace()))


def test_canonical_store_guard_rejects_bare_historical_tickets_flag():
    mongo = SimpleNamespace(
        ticket_setup=SetupCollection({"ticket_store": "tickets"}),
    )
    with pytest.raises(thread_service.ThreadConfigurationError, match="migrate-store"):
        asyncio.run(thread_service.ensure_canonical_ticket_store(mongo))


def test_explicit_source_staff_thread_must_be_private():
    rest = SimpleNamespace(fetch_channel=lambda _channel_id: None)

    async def fetch_channel(_channel_id):
        return SimpleNamespace(
            id=3,
            guild_id=1,
            parent_id=2,
            type=hikari.ChannelType.GUILD_PUBLIC_THREAD,
        )

    rest.fetch_channel = fetch_channel
    with pytest.raises(legacy_migration.LegacyMigrationError, match="private"):
        asyncio.run(legacy_migration._discover_staff_thread(
            rest,
            source_guild_id=1,
            source_channel_id=2,
            explicit_id=3,
            stored_id=None,
        ))


def test_conflicting_source_records_across_stores_fail_preview():
    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def limit(self, _amount):
            return self

        async def to_list(self, **_kwargs):
            return list(self.rows)

    class Collection:
        def __init__(self, rows):
            self.rows = rows

        def find(self, _query):
            return Cursor(self.rows)

    mongo = SimpleNamespace(
        tickets=Collection([{"_id": "canonical"}]),
        button_store=Collection([{"_id": "legacy"}]),
    )
    with pytest.raises(legacy_migration.LegacyMigrationError, match="conflicting"):
        asyncio.run(legacy_migration._legacy_source_ticket(mongo, 1, 2))
