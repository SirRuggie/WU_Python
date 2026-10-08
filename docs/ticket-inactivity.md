# Ticket inactivity review

Live thread tickets still marked **open** receive a recruiter review prompt after
seven days without a human message in the applicant-facing thread. Messages from
either the applicant or a recruiter count, including links, GIFs, and attachments.
Bot messages and discussion in the private staff thread do not reset this clock.

The prompt appears in that ticket's staff thread and mentions its configured
recruitment role. It asks whether to apply **Ghosted** and deny the ticket:

- **Yes - Deny** opens a required denial-reason form. Submitting it uses the normal
  denial workflow with the entered reason and ensures a persistent Ghosted flag
  exists. New flags use the entered reason; existing Ghosted reasons are preserved.
  Closing the form makes no decision and leaves the review pending.
- **No - Wait** leaves the ticket open and starts a new configured interval from the click.

Only authorized recruiters can act. Form submission rechecks permission and the
current prompt before saving the reason and denying; opening a form alone never
reserves or resolves the ticket. A new applicant-thread message, replacement
prompt, or completed decision makes an older prompt ineligible. Activity and prompt
identity are checked in the same MongoDB conditional update that commits a denial,
so a message arriving during a slow account lookup prevents a stale denial.
Ordinary manual Approve/Deny actions keep their existing revision behavior.

One unanswered prompt remains pending rather than pinging staff every day.
Approved and denied tickets are not reopened for inactivity review. Legacy tickets
and isolated testing tickets are excluded.

Activity and prompt state live with the existing ticket document in MongoDB. Flags
remain in the existing persistent flag storage; changing ticket status does not
remove a Ghosted flag. Pending work is recoverable after a bot restart.

## Temporary testing interval

`ticket_setup` → `_id: config` → `ticket_inactivity_minutes` can override the
seven-day default. The testing interval was restored to **7 days (10080 minutes)**
on September 28, 2026, after testing was confirmed complete. Prompt text uses the same
configured interval, and No starts a fresh interval. The worker checks about once
a minute. Existing prompts cannot deny a ticket that is not yet due under a newly
increased interval.

## Automatic archival of resolved tickets

The console **Admin Settings** button opens private, administrator-only Ticket
Settings. **Automatic Archive Timing** sets the number of quiet days for approved,
denied, or closed ticket pairs (default **1 day**; **0** disables cleanup).
Open-ticket inactivity review remains separate at **7 days**.

Cleanup runs once daily after ticket startup recovery is ready, and persists its
last completion time across restarts. Human messages in either the recruit thread
or staff thread protect both threads. Bot/webhook messages do not reset the clock.
The decision itself also starts a fresh quiet period. History is fetched from
Discord; inaccessible or inconclusive history is skipped. Activity is checked
again around archival, and a detected concurrent conversation or reopened ticket
restores the threads changed by that pass.

Archival preserves history and the application decision, and does not add locks.
A failed partial pair operation attempts to restore the thread already archived.
Legacy channel tickets and isolated test tickets are excluded.
