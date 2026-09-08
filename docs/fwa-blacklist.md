# FWA blacklist

An ongoing, staff-maintained list of opponent clans blacklisted from FWA wars
(clans that specifically target FWA clans for easy wins). There is no
automated feed for this: ChocolateClash is Cloudflare-blocked with no API
(see the FWA-sites-access notes in memory), so the bot cannot look up "is
this clan a known blacklisted clan" on its own. Every entry gets in either
through `/fwa war-plans` or by hand.

## What is stored

`utils/fwa_blacklist.py` owns the shape and every read/write. Documents live
in `mongo.fwa_blacklist`, keyed by the sanitized tag (`utils.fwa_points_parser
.sanitize_tag` — uppercase, no `#`):

```
{
    "_id": "ABC123",
    "name": "Some Clan",
    "added_at": "2026-09-08T12:00:00+00:00",   # ISO, set once, never overwritten
    "added_by_id": 123456789012345678,
    "added_by_name": "SomeStaffer",
    "source": "war-plans" | "manual",           # set once, never overwritten
    "last_seen_clan_tag": "ABCDE",                # our clan tag, most recent sighting
    "last_war_end_time": "2026-09-08T20:00:00",   # ISO, most recent sighting
}
```

`add_blacklisted(...)` upserts in one atomic `update_one`: `$setOnInsert` for
`added_at`/`added_by_id`/`added_by_name`/`source` (kept exactly as first
recorded), `$set` for `name`/`last_seen_clan_tag`/`last_war_end_time` (always
refreshed to the latest sighting). `remove_blacklisted`, `is_blacklisted`,
`blacklisted_tags` (batched `$in` check) and `list_blacklisted` (sorted by
name) round out the module.

## How entries get in

- **`/fwa war-plans`**, plan type **Blacklisted** — after the war-plan message
  posts, the command reads the clan's *current* war via the CoC API
  (`get_clan_war`) and, if it is in preparation or in war with a resolvable
  opponent, adds that opponent — tag and name **from the API**, not the
  free-text opponent name staff typed — with `source: "war-plans"`. If the
  war cannot be read (private log, no active war, any API error), the war
  plan still posts; the ephemeral confirmation says nothing was added and to
  use `/fwa blacklist add` instead. This never fails the command.
- **`/fwa blacklist add <tag> [name]`** — manual entry, `source: "manual"`.
  If `name` is left blank it is looked up from the CoC API. Gated by the same
  FWA Clan Rep role check as `/fwa war-plans`.
- **`/fwa blacklist remove <tag>`** — same role gate.
- **`/fwa blacklist list`** — read-only, no gate; says "empty" when there is
  nothing on the list.

## How it shows up elsewhere

- **`/todo` War view** (`extensions/commands/todo.py`): `_load_fwa_records`
  cross-checks each loaded `fwa_points` record's `scraped_opponent_tag`
  against the blacklist on every load (`blacklisted_tags`, one batched query)
  and sets `opponent_blacklisted: True` on the record in memory — so an
  opponent blacklisted *after* the points scrape still renders correctly, not
  just what was known at scrape time. `_fwa_suffix` then shows
  ` 🚫 BLACKLISTED` in place of `(FWA)`/`(not FWA)`; the WIN/LOSE verdict half
  of the line is unaffected. See [todo-dashboard.md](todo-dashboard.md).
- **FWA points monitor** (`extensions/tasks/fwa_points_monitor.py`):
  `store_record` sets `opponent_blacklisted` (bool) on the record itself via
  `is_blacklisted`, using the CoC-confirmed opponent tag. This is a point-in
  -time snapshot from when the war was caught up — `/todo`'s re-check above
  is what stays current if the blacklist changes afterward.

## Limitation

There is no ChocolateClash association check. This list only ever contains
what staff put on it, either by picking "Blacklisted" in `/fwa war-plans`
(which is only as good as the FWA rep's judgment call that war) or by adding
a clan by hand. Treat it as a staff record, not a verified database.

## Bulk import

`tools/import_fwa_blacklist.py` is a one-shot, idempotent importer for a
ChocolateClash blacklist export in markdown (a `Retrieved:`/`Source:` header
followed by a "## Clan list" table, one row per clan: name, backtick-quoted
tag, the site's classification, and a `[View]` link). Each row upserts
through `add_blacklisted` with `added_by_id=0`, `added_by_name="import"`,
`source="import"` (which only take effect on first insert -- an existing
entry's `added_at`/`added_by_id`/`added_by_name`/`source` are never
overwritten), then `$set`s `classification`, `imported_from` (the export's
Source url) and `retrieved_at` (the export's Retrieved date) on the same
document. Re-running the same file only refreshes those fields; it never
duplicates or re-attributes an entry.

```
venv/bin/python tools/import_fwa_blacklist.py path/to/blacklisted-clans.md --dry-run
venv/bin/python tools/import_fwa_blacklist.py path/to/blacklisted-clans.md
venv/bin/python tools/import_fwa_blacklist.py path/to/blacklisted-clans.md --only-fwa
```

`--dry-run` prints the same summary (rows parsed, inserted vs. updated,
per-classification counts, unparsed rows) without writing, using one `$in`
query to know which tags already exist. `--only-fwa` imports only rows whose
classification is exactly "FWA Blacklisted"; the default imports every
classification the export contains.
