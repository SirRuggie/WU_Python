"""Explicit scheduler-install contract for pre-existing bridge adapter tests.

These tests simulate a successful installer; native scheduler proof is covered by
 test_reminder_schedule_ack.py. Snapshot before the callback so racing edits are
not acknowledged as installed. No production code uses this helper.
"""

from utils import cwl_campaign as campaign, cwl_web_bridge as bridge


async def reconcile_installed(mongo, callback, *, guild_id):
    state = getattr(mongo, "_fixture_schedule_install", None)
    if state is None:
        state = {"generations": None}
        mongo._fixture_schedule_install = state

    async def install():
        rows = await mongo.bot_config.find(
            {
                "guild_id": guild_id,
                "kind": {"$in": ["cwl_campaign_defaults", "cwl_campaign_cycle"]},
                "activated": True,
            }
        ).to_list(length=None)
        cycles = {row["cycle"] for row in rows if row.get("cycle")}
        generations = {
            cycle: bridge.campaign_generation(
                await campaign.load_campaign(mongo, guild_id, cycle)
            )
            for cycle in cycles
        }
        await callback()
        state["generations"] = generations
        await bridge.mark_worker_alive(
            mongo, guild_id, worker_epoch="adapter-fixture", schedule_ready=True
        )

    return await bridge.reconcile_campaign_changes(
        mongo,
        install,
        guild_id=guild_id,
        loaded_generations=lambda: state["generations"],
        runtime_id="adapter-fixture",
    )
