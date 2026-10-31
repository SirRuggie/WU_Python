# Per-use command recipients

## Trigger-message deletion — released October 30, 2026

`trigger-delete-1` (PR #63, `b517afd46ecfa9cc08488798eba53393ed5b649f`)
adds **Delete the trigger message**, default-on for new and existing commands
through a read default. Saves, revisions and history retain the field; no
destructive migration is required. Both plain and recipient triggers delete the
member's message only after the reply succeeds. Disabled/unknown commands,
duplicate-guard suppression and failed replies never delete the trigger.
Turning the option off retains it. A missing original message is harmless.

Deletion permission/transport failures leave the successful reply delivered and
record `last_delete_error` with time, channel and reason. The editor exposes the
warning and Manage Messages guidance; a later successful delete clears it.
This state does not authorize replaying a reply or sending a test automatically.

The frontend/backend/bot release and Claude's read-only 360px smoke passed.
Codex and Claude did not send a live Discord trigger; Ruggie's own `!lazy` check
is separate. See [release evidence and rollback](dashboard-backend-releases.md#trigger-delete-1--october-30-2026).

## Recipient behavior

In Command triggers, enable **Let members add @person or @role**. Members type
`!command @person` or `!command @role`. A missing recipient produces usage guidance;
no saved reply is delivered. The selected recipient must be a current server member
or role. Unmentionable roles require the invoking member's MENTION_ROLES permission.
The mention appears inside the card, or above the text when there is no card.

The selected recipient is allowed to ping. Other saved mentions ping only when
**Ping the people and roles in this reply** is on. No DMs are sent. Discord's
permissions and personal notification preferences still apply; mocked payload
tests do not prove live notification delivery.

The old `text_command_recipients.start()` picker had no production caller: the
prefix handler already used the inline path. Its unused component route and module
were removed in command-triggers-2. No new picker state was reachable; old state
expires through the existing component-state TTL. Inline user/role, mention scope,
exact-match, missing-recipient and failed-delivery tests remain.

Command input now escapes the hyphen for browser `v`-flag validation. Replies
outside configured channel or role scope are silent and do not delete the trigger.
Usage outcomes use safe reasons; uncertainty never automatically resends a reply.
