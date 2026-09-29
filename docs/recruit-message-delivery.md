# Recruitment message delivery IDs

Find these records in **MongoDB → settings → recruit_message_deliveries**.
They cover Goblin prompts, Goblin success confirmations, and Family Code success
confirmations. They contain no message bodies, recruit answers, or interaction
tokens. User-facing messages and styling are unchanged.

## Find a delivery

From the bot checkout, using its virtualenv:

```sh
venv/bin/python tools/inspect_recruit_deliveries.py --user-id 123456789
venv/bin/python tools/inspect_recruit_deliveries.py --channel-id 123456789
venv/bin/python tools/inspect_recruit_deliveries.py --status needs_review
venv/bin/python tools/inspect_recruit_deliveries.py --delivery-id 'family_code_confirmation:CHANNEL:USER:SESSION'
```

Use `.venv/bin/python` in the development checkout. The tool loads that checkout's
`.env`, only reads Mongo, and never sends or retries a message. Results show the
newest 20 records by default; `--limit` accepts 1–100. A confirmed message includes
a Discord link. Logs use `recruit_delivery_sent`, `recruit_delivery_needs_review`,
and `recruit_delivery_reconcile_failed`, with the readable `delivery_id`.

## What the fields mean

- `_id`: readable identity `MESSAGE_KIND:CHANNEL_ID:RECRUIT_ID:SESSION_ID`.
- `kind`: `goblin_prompt`, `goblin_confirmation`, or `family_code_confirmation`.
- `discord_nonce`: a deterministic 24-character version of that identity, sent
  to Discord on every attempt. Hikari enables Discord's `enforce_nonce` for it.
- `discord_message_id`: the message Discord accepted or the history check found.
- `attempts`: send attempts, including failures—not the number of posted messages.
- `first_attempt_at`: anchors the short retry window; retries do not extend it.
- `last_error`: exception class or `prior_delivery_unconfirmed`; no raw tokens.
- `recovered_from_history`: true when a later history check found the message.
- `claim_id` / `lease_until`: internal ownership of a two-minute processing lease.
- `schema_version`: currently 1. Dates are UTC.

| Status | Meaning |
| --- | --- |
| `prepared` | Saved before sending. |
| `sending` | A worker holds the delivery lease; a stopped worker's lease expires. |
| `retryable` | An attempt failed or timed out. Retry still follows the time/history rules below. |
| `sent` | Message ID saved; subsequent attempts return this ID without sending. |
| `needs_review` | Prior delivery could not be confirmed; no replacement was sent. |

## Retry and restart behavior

The delivery ID is saved **before** calling Discord. Retries within 60 seconds
of the first attempt reuse its nonce. Discord's same-author nonce protection
lasts a few minutes; the bot deliberately uses a shorter retry window.

After that window, the bot checks up to 500 messages after the original attempt
for the exact nonce **and this bot's author ID**. A match completes the receipt
without posting again. If history is unavailable, the nonce is missing, or no
match is found within the bound, it records `needs_review`. Absence is not proof
that Discord never accepted the message. A later normal retry can check history
again, but does not blindly resend. An initial definite HTTP rejection (such as
Forbidden) can be retried as a fresh send because Discord rejected that request.

Claims and IDs survive restart in Mongo. Recovery runs on the next normal
challenge retry/valid reply; this is not a background message resending queue.
Goblin retries from the same Shield message retain the same challenge session.
The independent Shield receipt still permanently suppresses already-used buttons.

## If a record needs review

Look it up by recruit ID, channel ID, or `--status needs_review`, then inspect the
channel around `first_attempt_at`. Give the delivery ID to the maintainer for
reconciliation. **Do not delete/reset the receipt to force a retry**: the original
message may already exist. The diagnostic tool intentionally has no resend or
state-edit option. Successful evidence-based reconciliation must also preserve
the existing challenge/session ownership checks.

Receipt retention is 30 days, with a Mongo TTL index on `expires_at`. This exceeds
the 24-hour challenge lifetime. Additional indexes support status and recruit/channel
lookups. Startup ensures the indexes exist. Existing challenge records remain in
`settings.recruit_challenges`; nothing is placed in `button_store`. This applies
to new delivery attempts, not historical messages already sent before deployment.

Discord sends and Mongo writes are not a single transaction. This reduces the
ambiguous-delivery risk, but does not promise unlimited exactly-once delivery.
When evidence is insufficient, avoiding a duplicate takes precedence over
silently repeating a message.
