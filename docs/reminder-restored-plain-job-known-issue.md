# Existing restored plain reminder removed by the following sync

This is a separate, pre-existing issue reported in Claude review142; no fix is
included in the acknowledgement work. No production data or Discord send was used.

Local reproduction uses the actual native scheduler with MemoryMongo and
MemoryScheduler from `tests/test_reminder_schedule_ack.py`:

1. Activate default settings and freeze November22,2026 at noon New York time.
2. Persist an unsent signup/main occurrence from one hour earlier with the current
   generation, `job_kind="scheduled"`, and zero failures.
3. Call `restore_pending_reminders()`: the job is restored for five seconds later,
   and both scheduler and durable pending record contain it.
4. Call `sync_campaign_schedule(guild_id, "2026-11")` immediately: both disappear.
   The sender mock has zero calls.

The restore preserves the ordinary scheduled kind. The following native sync
preserves pending manual/retry/failed jobs, but an ordinary overdue occurrence
is not in its desired future schedule. It removes the restored plain job.

Executable local evidence: `.local/p142-missed-reproducer.py` and
`.local/p142-missed-reproducer.log` (one passing reproduction). These files are
workspace evidence, not production configuration. Baseline presence is from
Claude's independent review; this local reproduction confirms the current
behaviour without changing it. Scope and a safe delivery policy need a separate
owner decision, especially because an uncertain send must not be retried blindly.
