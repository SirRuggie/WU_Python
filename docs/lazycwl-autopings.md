# LazyCWL auto-pings — RETIRED

Retired 2026-09-12. Replaced by [`lazycwl-dashboard.md`](lazycwl-dashboard.md)
("Reminders" section) — the `/fwa lazycwl-autopings-*` commands this file
described no longer have their own implementation; they are now redirect
aliases that open `/lazycwl` (see `extensions/commands/fwa/lazy_cwl.py`).

Two facts from the retired implementation are still true of the new one and
worth restating here: the ping channel is still hard-coded (unchanged
constant, now `PING_CHANNEL` in `extensions/commands/fwa/lazy_cwl_service.py`),
and the select-all pattern (`SelectOption(value="ALL")`, 🌍 label, handlers
branching on `if selection == "ALL":`) lives on in the dashboard as its own
`ALL` action_id value on every S0-S6 screen.
