# `/clear-my-dms`

`/clear-my-dms` is a self-service command that works only in the requester's
one-to-one DM with WUBOT. It confirms before deleting every WUBOT-authored
message up to and including the confirmation message, regardless of age. It
never deletes the requester's messages.

The confirmation is bound to that user and DM for ten minutes. Confirm and
cancel use a single atomic state transition, so duplicate or stale clicks do
not start a second purge. The history is streamed through Hikari's paginator
and each message is deleted individually; Discord REST rate-limit handling is
therefore retained and there is no bulk-delete age restriction.

Before scanning, the command stops the active automatic `/todo` panel under
the same lock used by its scheduler. New notifications and a new `/todo`
panel sent after the fixed confirmation cutoff remain enabled. A brief normal
DM receipt is posted after a completed or partial sweep and removes itself
after 15 seconds.
