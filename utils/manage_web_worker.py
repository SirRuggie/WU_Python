"""Bot-owned web management operations; durable claim before any side effect."""

import asyncio
import time
import logging
import weakref
from types import SimpleNamespace as NS
from datetime import datetime, timezone, timedelta
import hikari
from pymongo import ReturnDocument
from utils.member_profiles import ProfileOutcomeUncertain

WORKER_ID = "manage-web-worker:644963518025826315"
GUILD_ID = 644963518025826315
ACTIONS = {
    ("roles", "bulk_one"),
    *{("member_profiles", x) for x in ("save", "import", "standardize_one")},
    ("clans", "emoji"),
    ("clans", "thread"),
    ("fwa_points", "enable"),
    ("fwa_points", "disable"),
    ("fwa_sync", "check_feed"),
    ("fwa_sync", "test_dm"),
    ("band_monitor", "status"),
    ("band_monitor", "debug_on"),
    ("band_monitor", "debug_off"),
    ("ticket_settings", "save"),
    ("ticket_settings", "check"),
    ("ticket_settings", "restore_entry"),
    ("ticket_settings", "restore_console"),
    ("ticket_testing", "start"),
    ("ticket_testing", "end"),
    ("ticket_testing", "access"),
    ("ticket_testing", "main"),
    ("ticket_testing", "fwa"),
    ("ticket_testing", "clear"),
    *{
        ("cwl_rosters", x)
        for x in (
            "save",
            "replace",
            "clear",
            "add",
            "remove",
            "send",
            "schedule",
            "start",
            "pause",
            "resume",
            "away",
        )
    },
    ("recruit", "send"),
    ("recruit", "update"),
}


async def context(bot, mongo, row):
    from extensions.commands.recruit.perms import guild_permissions
    from utils.dashboard_access import dashboard_allowed as allowed

    if row.get("section") == "roles":
        from extensions.member_role_dashboard import request_context

        return await request_context(bot, mongo, row)
    if row.get("section") == "member_profiles":
        from extensions.warrior.profile_dashboard import request_context

        return await request_context(bot, mongo, row)
    user = await bot.rest.fetch_member(GUILD_ID, int(row["user_id"]))
    role_list = await bot.rest.fetch_roles(GUILD_ID)
    guild = await bot.rest.fetch_guild(GUILD_ID)
    role_map = {r.id: r for r in role_list}
    view = NS(id=GUILD_ID, owner_id=guild.owner_id, get_role=role_map.get)
    permissions = guild_permissions(user, view)
    member = NS(
        id=user.id,
        guild_id=GUILD_ID,
        role_ids=user.role_ids,
        permissions=permissions,
        display_name=user.display_name,
        get_roles=lambda: [r for r in role_list if r.id in user.role_ids],
    )
    actor = {
        "user_id": str(user.id),
        "role_ids": set(map(int, user.role_ids)),
        "permissions": int(permissions),
        "guild_owner": user.id == guild.owner_id,
        "dashboard": True,
    }
    if not await allowed(actor, row["section"], mongo):
        raise ValueError("Your Discord access changed. This action was not run.")

    async def noop(*args, **kwargs):
        return None

    captured = []

    async def respond(*args, **kwargs):
        if kwargs.get("content"):
            captured.append(str(kwargs["content"]))

    interaction = NS(
        app=bot,
        guild_id=GUILD_ID,
        member=member,
        application_id=bot.get_me().id,
        edit_initial_response=respond,
        create_initial_response=noop,
    )
    return NS(
        user=user,
        member=member,
        guild_id=GUILD_ID,
        interaction=interaction,
        defer=noop,
        respond=respond,
        captured=captured,
        dashboard_actor=actor,
    )


async def dispatch(bot, mongo, row, ctx):
    section, action, values = row["section"], row["action"], row["values"]
    if (section, action) not in ACTIONS or not isinstance(values, dict):
        raise ValueError("Unknown management action.")
    if section == "roles":
        from extensions.member_role_dashboard import apply

        return await apply(bot, mongo, row, ctx)
    if section == "member_profiles":
        from extensions.warrior.profile_dashboard import apply

        return await apply(bot, mongo, row, request_context=ctx)
    if section == "clans":
        from utils.manage_operations_runtime import revision
        from cwl_web.manage_clans import audit
        from utils.clan_dashboard_actions import replace_emoji, ensure_thread

        clan = await mongo.clans.find_one({"tag": values.get("tag")})
        if not clan or revision(clan) != row["revision"]:
            raise ValueError("Clan changed. Reload and review before trying again.")
        await audit(mongo, {"user_id": row["user_id"]}, "before_" + action, clan)
        if action == "emoji":
            if not clan.get("logo"):
                raise ValueError("Save a clan logo first.")
            await replace_emoji(bot, mongo, clan, clan["logo"])
        else:
            await ensure_thread(bot, mongo, clan, GUILD_ID)
        return {
            "message": (
                "Clan emoji updated." if action == "emoji" else "Clan thread ready."
            )
        }
    if section == "ticket_testing":
        for key in ("allowed_user_ids", "allowed_role_ids"):
            if key in values and (
                not isinstance(values[key], list)
                or len(values[key]) > 25
                or any(
                    not isinstance(v, (str, int)) or not str(v).isdigit()
                    for v in values[key]
                )
            ):
                raise ValueError("Choose up to 25 valid members or roles.")
        if "allow_admins" in values and type(values["allow_admins"]) is not bool:
            raise ValueError("Choose whether administrators are allowed.")
    if section == "cwl_rosters" and action in {"start", "resume", "schedule"}:
        if type(values.get("every_minutes", 60)) is not int or values.get(
            "every_minutes", 60
        ) not in (30, 60, 120):
            raise ValueError("Choose every 30 minutes, 1 hour, or 2 hours.")
    if section in {"fwa_points", "fwa_sync"}:
        from utils.manage_operations_runtime import revision

        collection = (
            mongo.fwa_points if section == "fwa_points" else mongo.fwa_sync_config
        )
        current = await collection.find_one({"_id": "config"}) or {}
        if revision(current) != row["revision"]:
            raise ValueError("Settings changed. Reload and review before trying again.")
        if section == "fwa_points":
            from extensions.tasks import fwa_points_monitor

            stopped = await fwa_points_monitor.set_monitor_enabled(
                mongo, action == "enable", expected_config=current
            )
            return {
                "message": f"Points monitoring {'enabled' if action=='enable' else 'disabled'}. {stopped} pending checks stopped."
            }
        from extensions.tasks import band_sync_ical as sync

        config = await sync.load_config(mongo)
        events, errors = await sync.collect_events(config["summary_filter"])
        if action == "check_feed":
            return {
                "message": f"Found {len(events)} upcoming events. {len(errors)} feed errors. No messages sent."
            }
        event = (
            events[0]
            if events
            else {
                "uid": "preview",
                "start": datetime.now(timezone.utc) + timedelta(minutes=61),
                "end": datetime.now(timezone.utc) + timedelta(minutes=101),
                "summary": "PREVIEW — Sync reminder",
                "calendar": "Sync3",
            }
        )
        await sync.send_test_dm(
            int(row["user_id"]),
            sync.build_embed(
                event,
                (str(config["offsets"][0]) if config["offsets"] else "discovery"),
            ),
        )
        return {"message": "Test reminder sent to your Discord DMs."}
    if section == "band_monitor":
        from extensions.tasks import band_monitor as monitor

        if action != "status":
            monitor.DEBUG_MODE = action == "debug_on"
        from utils.manage_operations_runtime import runtime_snapshot

        await mongo.bot_config.update_one(
            {"_id": "manage-web-band-status"},
            {"$set": runtime_snapshot(monitor)},
            upsert=True,
        )
        if action == "status":
            return {"message": "BAND status refreshed."}
        return {
            "message": f"BAND debug is {'on' if monitor.DEBUG_MODE else 'off'}. This resets when the bot restarts."
        }
    if section == "ticket_settings":
        from extensions.commands.tickets import settings

        cfg = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        from cwl_web.manage_content import fingerprint

        if fingerprint(cfg) != row["revision"]:
            raise ValueError("Ticket settings changed. Reload before trying again.")
        if action == "save":
            from cwl_web.manage_tickets import validated_settings

            changes = validated_settings(values)
            from cwl_web.change_history import begin, finish
            from cwl_web.manage_tickets import history_values

            histories = []
            actor = {
                "user_id": str(row["user_id"]),
                "member": {
                    "nick": getattr(ctx.member, "display_name", str(row["user_id"]))
                },
            }
            for part in ("timers", "main", "fwa", "viewers"):
                before = history_values(cfg, part)
                if set(before).intersection(changes):
                    token = await begin(
                        mongo,
                        "/api/cwl/manage/ticket-settings/" + part,
                        actor,
                        before,
                        row.get("history_action", "edit"),
                    )
                    histories.append((token, part))
            result = await settings.save(
                ctx,
                mongo,
                bot.rest,
                {"draft": dict(cfg, **changes), "baseline": cfg},
            )
            fresh = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
            for token, part in histories:
                await finish(mongo, token, history_values(fresh, part))
            return {"message": result}
        if action == "check":
            await settings.validate(mongo, bot.rest, cfg, GUILD_ID)
            return {
                "message": "Ticket channels, permissions, and entry binding are valid."
            }
        if action == "restore_entry":
            message = await settings.repair_entry(ctx, mongo, bot)
            return {"message": message}
        from extensions.commands.tickets import console

        await console.configure_hub_here(
            bot,
            mongo,
            guild_id=GUILD_ID,
            channel_id=int(values.get("console_channel") or 0),
        )
        return {"message": "Staff console checked."}
    if section == "ticket_testing":
        from utils import ticket_testing_control as control
        from extensions.commands.tickets import testing_service
        from cwl_web.manage_content import fingerprint

        current = await testing_service.active_window(testing_service.test_mongo(mongo))
        if fingerprint(current) != row["revision"]:
            raise ValueError("The test window changed. Reload before trying again.")
        if action == "start":
            await control.start_window(
                bot,
                mongo,
                ctx,
                int(values.get("duration_minutes", 60)),
                int(values.get("cleanup_minutes", 60)),
            )
        elif action == "end":
            await control.end_window(bot, mongo, ctx)
        elif action == "clear":
            await testing_service.request_clear(testing_service.test_mongo(mongo))
        elif action == "access":
            await control.update_access(
                bot,
                mongo,
                ctx,
                user_ids=values.get("allowed_user_ids", []),
                role_ids=values.get("allowed_role_ids", []),
                allow_admins=values.get("allow_admins", True),
            )
        else:
            await control.open_test_ticket(ctx, bot, mongo, action)
        return {"message": "Test ticket action completed. " + " ".join(ctx.captured)}
    if section == "cwl_rosters":
        from extensions.commands.fwa import lazy_cwl_service as service
        from utils import lazy_cwl_store as store
        from bson import ObjectId

        tag = values["clan_tag"]
        pool = store.normalize_section(values["section"])
        current = await store.get_active(mongo, tag, section=pool)
        from cwl_web.manage_content import fingerprint

        if fingerprint(current) != row["revision"]:
            raise ValueError(
                "This saved clan changed. Reload and review before trying again."
            )
        if action == "schedule":
            from utils.return_schedule import validate_window

            if pool != "FWA" or current is None:
                raise ValueError("Only saved FWA lists can be scheduled.")
            validate_window(
                values.get("schedule_start"),
                values.get("schedule_end"),
                current,
            )
        expected = current["_id"] if current else None
        kwargs = dict(section=pool, expected_list_id=expected)
        if action == "send":
            from utils.return_reminder_settings import destination

            if not values.get("destination") or int(
                values["destination"]
            ) != await destination(mongo, pool):
                raise ValueError(
                    "Return channel changed. Reload and review before sending."
                )
        try:
            if action == "save":
                result = await service.save_list(tag, int(row["user_id"]), **kwargs)
            elif action == "replace":
                result = await service.replace_list(tag, int(row["user_id"]), **kwargs)
            elif action == "clear":
                result = await service.finish(tag, **kwargs)
            elif action == "add":
                result = await service.add_player_by_tag(
                    tag, values["player_tag"], **kwargs
                )
            elif action == "remove":
                result = {
                    "removed": await store.remove_players(
                        mongo, tag, values["player_tags"], **kwargs
                    )
                }
            elif action == "send":
                result = await service.remind_now(
                    tag, expected_channel=values.get("destination"), **kwargs
                )
            elif action == "schedule":
                result = await service.set_reminders(
                    tag,
                    True,
                    int(values.get("every_minutes", 60)),
                    schedule={
                        "start": values["schedule_start"],
                        "end": values["schedule_end"],
                    },
                    expected_reminders=current.get("reminders") or {},
                    **kwargs,
                )
            elif action == "start" and current is None:
                result = await service.capture_and_start_returns(
                    tag,
                    int(row["user_id"]),
                    int(values.get("every_minutes", 60)),
                    section=pool,
                )
            elif action == "start":
                result = await service.set_reminders(
                    tag,
                    True,
                    int(values.get("every_minutes", 60)),
                    start_now=True,
                    expected_reminders=(
                        current.get("reminders") or {} if current else {}
                    ),
                    **kwargs,
                )
            elif action == "away":
                result = (
                    {"accounts": await service.away_players(current)}
                    if current
                    else {"accounts": []}
                )
            else:
                result = await service.set_reminders(
                    tag,
                    action != "pause",
                    int(values.get("every_minutes", 60)),
                    **kwargs,
                )
        except Exception as exc:
            raise RuntimeError("Native action outcome needs checking") from exc
        if isinstance(result, dict) and result.get("error"):
            raise ValueError(str(result["error"]))
        if action == "away":
            accounts = [
                {
                    "tag": p.get("tag", ""),
                    "name": p.get("name") or p.get("tag", ""),
                }
                for p in result["accounts"]
            ]
            return {
                "message": f"{len(accounts)} saved accounts are away from this clan.",
                "accounts": accounts,
            }
        summary = []
        if isinstance(result, dict):
            for key, label in (
                ("removed", "Players removed"),
                ("saved_count", "Players saved"),
                ("sent", "Reminders sent"),
                ("failed", "Failed deliveries"),
                ("skipped", "Skipped"),
            ):
                if key in result and isinstance(result[key], (int, str, bool)):
                    summary.append(f"{label}: {result[key]}")
        return {
            "message": "Return reminder action completed.",
            "details": "\n".join(summary),
        }
    if section == "recruit":
        from cwl_web.manage_delivery import publish

        return await publish(bot, mongo, row, ctx)
    raise ValueError("Unknown management action.")


async def _heartbeat(mongo):
    while True:
        await mongo.bot_config.update_one(
            {"_id": WORKER_ID},
            {"$set": {"checked_at": time.time()}},
            upsert=True,
        )
        await asyncio.sleep(20)


_QUEUE_LOCKS = weakref.WeakKeyDictionary()


def queue_lock():
    return _QUEUE_LOCKS.setdefault(asyncio.get_running_loop(), asyncio.Lock())


async def poll(bot, mongo, *, fast=False, known_work=False):
    lock = queue_lock()
    if lock.locked():
        return 0
    async with lock:
        if fast and not known_work and not await ready_work(mongo):
            return 0
        task = asyncio.create_task(_heartbeat(mongo))
        try:
            if fast:
                return await _process_requests(bot, mongo)
            return await _poll(bot, mongo)
        finally:
            task.cancel()
            import contextlib

            with contextlib.suppress(asyncio.CancelledError):
                await task


_WORK_INDEXES = weakref.WeakKeyDictionary()
_OTHER_WINDOWS = weakref.WeakKeyDictionary()


async def ready_work(mongo):
    from utils.member_profile_runs import ProfileRuns

    loop = asyncio.get_running_loop()
    if _WORK_INDEXES.get(loop) is not mongo:
        await ProfileRuns(mongo).ensure_work_index()
        _WORK_INDEXES[loop] = mongo
    started = time.perf_counter()
    work = await ProfileRuns(mongo).ready_work()
    if work:
        logging.getLogger(__name__).info(
            "Management timing stage=ready_lookup run=%s elapsed_ms=%.2f next_in_ms=%.2f",
            work.get("_id", "-"),
            1000 * (time.perf_counter() - started),
            1000 * max(0, work.get("next_at", 0) - time.time()),
        )
    return work


async def fast_poll(bot, mongo):
    # Idle: one indexed, projected query. Active work releases the lane between
    # checks so the bridge/fallback can proceed, without rounding pacing to ticks.
    work = await ready_work(mongo)
    while work:
        handled = await poll(bot, mongo, fast=True, known_work=True)
        remaining = work.get("next_at", 0) - time.time()
        delay = (
            min(1, max(0.05, remaining)) if remaining > 0 else (0.05 if handled else 1)
        )
        sleep_started = time.perf_counter()
        await asyncio.sleep(delay)
        logging.getLogger(__name__).info(
            "Management timing stage=scheduler_wake run=%s scheduled_ms=%.2f actual_ms=%.2f",
            work.get("_id", "-"),
            1000 * delay,
            1000 * (time.perf_counter() - sleep_started),
        )
        work = await ready_work(mongo)


async def _poll(bot, mongo):
    from utils.manage_operations_runtime import (
        refresh_base_image_cache,
        runtime_snapshot,
    )
    from extensions.tasks import band_monitor

    try:
        await refresh_base_image_cache(mongo)
        await mongo.bot_config.update_one(
            {"_id": "manage-web-band-status"},
            {"$set": runtime_snapshot(band_monitor)},
            upsert=True,
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "Management runtime snapshot unavailable", exc_info=True
        )
    await mongo.bot_config.update_one(
        {"_id": WORKER_ID}, {"$set": {"checked_at": time.time()}}, upsert=True
    )
    from utils.return_bulk import activate

    await activate(mongo)
    return await _process_requests(bot, mongo)


async def _process_requests(bot, mongo):
    from utils.member_profile_runs import ProfileRuns, ProfileRunStopped

    dispatch_started = time.perf_counter()
    try:
        await ProfileRuns(mongo).advance()
    except Exception:
        logging.getLogger(__name__).warning(
            "Member profile run scheduling unavailable", exc_info=True
        )
    advance_ms = 1000 * (time.perf_counter() - dispatch_started)
    sweep_started = time.perf_counter()
    # A crashed sending claim is never replayed: the Discord effect may exist.
    await mongo.bot_config.update_many(
        {
            "kind": "manage_web_request",
            "status": "running",
            "started_at": {"$lt": time.time() - 300},
        },
        {
            "$set": {
                "status": "uncertain",
                "finished_at": time.time(),
                "message": "The bot stopped before confirming this action. Check Discord before repeating it.",
            }
        },
    )
    sweep_ms = 1000 * (time.perf_counter() - sweep_started)
    handled = 0
    for _ in range(5):
        loop = asyncio.get_running_loop()
        window, used = _OTHER_WINDOWS.get(loop, (time.monotonic(), 0))
        if time.monotonic() - window >= 10:
            window, used = time.monotonic(), 0
        query = {"kind": "manage_web_request", "status": "pending"}
        if used >= 5:
            query["section"] = "member_profiles"
        claim_started = time.perf_counter()
        row = await mongo.bot_config.find_one_and_update(
            query,
            {"$set": {"status": "running", "started_at": time.time()}},
            return_document=ReturnDocument.AFTER,
        )
        if not row:
            break
        if row.get("section") == "member_profiles":
            logging.getLogger(__name__).info(
                "Management timing stage=claim_query request=%s elapsed_ms=%.2f advance_ms=%.2f expired_sweep_ms=%.2f dispatch_ms=%.2f",
                row["_id"],
                1000 * (time.perf_counter() - claim_started),
                advance_ms,
                sweep_ms,
                1000 * (time.perf_counter() - dispatch_started),
            )
        if row.get("section") != "member_profiles":
            used += 1
        _OTHER_WINDOWS[loop] = (window, used)
        handled += 1
        claimed = time.perf_counter()
        try:
            logging.getLogger(__name__).info(
                "Management timing stage=claimed request=%s section=%s action=%s queued_ms=%.2f",
                row["_id"],
                row.get("section"),
                row.get("action"),
                1000 * (time.time() - row["created_at"]),
            )
            if (
                row.get("guild_id") != GUILD_ID
                or (row["section"], row["action"]) not in ACTIONS
                or time.time()
                > min(
                    row.get("expires_at", row["created_at"] + 120),
                    row["created_at"] + 900,
                )
            ):
                raise ValueError(
                    "This request expired. Reload the page before trying again."
                )
            ctx = await context(bot, mongo, row)
            logging.getLogger(__name__).info(
                "Management timing stage=authorization request=%s elapsed_ms=%.2f",
                row["_id"],
                1000 * (time.perf_counter() - claimed),
            )
            result = await asyncio.wait_for(
                dispatch(bot, mongo, row, ctx),
                200 if row["section"] == "member_profiles" else 120,
            )
            update = {
                "status": "done",
                "message": result.get("message", "Completed."),
                "result": result,
            }
        except ProfileRunStopped as exc:
            update = {"status": "stopped", "message": str(exc)[:400]}
        except ProfileOutcomeUncertain as exc:
            update = {"status": "uncertain", "message": str(exc)[:400]}
            if isinstance(getattr(exc, "counts", None), dict):
                update["result"] = {"counts": exc.counts}
        except ValueError as exc:
            update = {"status": "failed", "message": str(exc)[:400]}
        except Exception as error:
            update = {
                "status": "uncertain",
                "message": "The bot could not confirm this action. Check Discord before repeating it.",
            }
            if row.get("section") == "member_profiles":
                retry_after = getattr(error, "retry_after", None)
                if isinstance(retry_after, (int, float)) and retry_after > 0:
                    update["retry_not_before"] = time.time() + retry_after
        await mongo.bot_config.update_one(
            {"_id": row["_id"], "status": "running"},
            {"$set": dict(update, finished_at=time.time())},
        )
        logging.getLogger(__name__).info(
            "Management timing stage=finished request=%s status=%s elapsed_ms=%.2f",
            row["_id"],
            update["status"],
            1000 * (time.perf_counter() - claimed),
        )
        if row.get("parent_id") and (row.get("section"), row.get("action")) in {
            ("member_profiles", "standardize_one"),
            ("roles", "bulk_one"),
        }:
            try:
                await ProfileRuns(mongo).advance()
            except Exception:
                logging.getLogger(__name__).warning(
                    "Member profile completion scheduling unavailable",
                    exc_info=True,
                )

    return handled
