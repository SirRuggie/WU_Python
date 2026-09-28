# Ticket inactivity review

Live thread tickets still marked **open** receive a recruiter review prompt after
seven days without a human message in the applicant-facing thread. Messages from
either the applicant or a recruiter count, including links, GIFs, and attachments.
Bot messages and discussion in the private staff thread do not reset this clock.

The prompt appears in that ticket's staff thread and mentions its configured
recruitment role. It asks whether to apply **Ghosted** and deny the ticket:

- **Yes** uses the normal denial workflow with the exact reason
  `Recruit stopped responding`, and ensures a persistent Ghosted flag exists.
- **No** leaves the ticket open and starts a new seven-day interval from the click.

Only authorized recruiters can act. A new applicant-thread message, replacement
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
seven-day default. It is currently set to **5 minutes** at the operator's request
for testing. Keep this override until the operator explicitly requests restoration;
setting it to `10080` or removing it restores seven days. Prompt text uses the same
configured interval, and No starts a fresh interval. The worker checks about once
a minute. Existing prompts cannot deny a ticket that is not yet due under a newly
increased interval.
