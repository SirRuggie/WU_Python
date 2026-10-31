# Command triggers redesign — development review

Prompt 31, branch `codex/command-triggers-2`. Not released.

## Permission QUESTION (report only)

`server_management.allowed` calls `dashboard_allowed` without the write flag for
browser actors. The current grant catalog has management scopes, including
`text_commands`; it has no view-only grant for this editor. The same explicitly
granted management scope consequently allows both reads and writes. The separate
`strikes_read` aggregation is a read route convenience; strike mutation routes
still request their distinct strike scopes. The legacy scope expansion and session
scope intersection remain in place. A hypothetical future view-only grant could
not be enforced by this branch without extending the policy; no permission behavior
was changed here. Should a separate view-only permission model be designed in a
follow-up? The characterization test records the current behavior; this is source
analysis, not a production write probe.

## Copy changes

- Text commands → Command triggers (documentation)
- Type a trigger like !trigger in Discord to post its saved reply → Type a command like !rules in Discord. The bot posts its reply.
- Enabled in Discord → On
- Message text (outside embed) → Text above the card
- Mentions & recipients → Pings
- Allow pings in message and embed → Ping the people and roles in this reply
- Mention a user or role with the trigger → Let members add @person or @role
- Anyone can use enabled commands. Replies appear in the same channel. → The reply appears in the same channel.
- Separator → Line; Media gallery → Image gallery; Text + accessory → Text with small image
- Message card → Card; Action buttons → Buttons; Dropdown → Menu
- Formatting guide → Formatting help; Appearance → Look; Delete command disclosure → Danger zone
- Change history → History

## Removed recipient path

Repository search found no caller of `text_command_recipients.start()`. Only its
old `cr:` dispatch handler and picker-specific tests referred to the module. Removed
that unused path and corrected the guide. Inline recipient payload/validation and
send-before-delete regression tests remain; no live Discord notification was sent.

## Verification in progress

Focused outcomes/history/runtime backend 83 passed before scope-choice additions;
rendered editor/history tests 5 passed. Full frontend's first root-directory run
was an invalid harness invocation (relative fixture paths); corrected working
directory run had one unrelated quick-selection timeout under concurrent test
load. Rerun with bounded workers is required. Full backend, browser and mutations
are not yet complete. No READY claim.
