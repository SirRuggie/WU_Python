# Existing restored plain reminder removed by the following sync

This is a separate, pre-existing issue reported in Claude review142; no fix is
included in the acknowledgement work. No production data or Discord send was used.

Local reproduction uses the actual native scheduler with MemoryMongo and
MemoryScheduler from `tests/test_reminder_schedule_ack.py`:

1. Activate default settings and freeze November22,2026 at noon New York time.
2. Persist the unsent signup/main occurrence at its actual template time,
   November20,2026 at17:00 New York time, with the current generation, `job_kind="scheduled"`, and zero failures.
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


## Acknowledgement scope clarified by Shaka433

The removed job is campaign-owned, not a legacy reminder:
`cwl_campaign:644963518025826315:2026-11:signup:main`, generation `1:0`.
After restore then sync/reconciliation, both native process proof and worker
acknowledgement report November/December `1:0` while that overdue job is absent.
All eight expected future November jobs (reminders2–5, both pools) are installed
exactly; twelve future December jobs and the rollover job are also installed.
There are no missing future November IDs. Exact local IDs/counts are retained in
`.local/p142-missed-scope.json`, with the actual template run time.

Shaka433 clarifies that `schedule_synced` acknowledges the exact current-policy
future desired schedule, not overdue catch-up. The missing restored overdue
occurrence is excluded from that acknowledgement contract and remains a separate
delivery-policy question for the owner. The existing native sync deliberately excludes past
ordinary scheduled occurrences; this acknowledgement patch does not change that
policy. No repair policy or send is introduced here. Zero mock sender calls are
only evidence that this fixture did not invoke the mock, not delivery evidence.
