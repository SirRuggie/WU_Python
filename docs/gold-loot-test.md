# Gold loot leaderboard

Run `/loot-leaderboard` in Warriors United. Update refreshes the same goldenrod
Components V2 message without pinging members. The small footer shows the start,
last refresh and tracked-player count. Ordinary command requests cache for 60
seconds; Update bypasses that cache. The message is not refreshed on a timer.

## Battle-loot correction

The corrected implementation sums ClashKing `/v2/player/{tag}/battlelog/history`
records for farming, ranked and legend attacks after the original per-player
capture timestamp. Gold Grab is not used for scoring: its 2-billion cap affected
28 of 44 starting accounts. Old achievement values are retained for reference.

Records persist in `loot_events`, keyed by player, timestamp and battle mode.
Repeated refreshes update an existing record instead of double counting. Missing
records in a later response do not delete stored loot. Failed queries preserve
saved totals and display a warning. The panel header shows only the leaderboard title and family scope.

ClashKing polls the official API: no guaranteed delay or complete-history
coverage is assumed. Backfilling after downtime depends on retained upstream
history. Totals include observed battle gold, not every reward or income source.
The original fixed roster remains tracked even if players leave the clan.

## Console and storage

Use `.venv/bin/python tools/gold_loot.py show` for saved results, `refresh` for
fresh data, or `watch` for five-minute polling. `--interval 60` selects one minute.
Stop watch with Ctrl+C. No separate watcher service is installed.

`start` captures a new clan roster using `COC_API_TOKEN` and refuses to overwrite
an existing test. Do not run start to recover this test. `--db PATH` selects a
separate database. Data lives in `.local/gold-loot.sqlite3` on the bot host and
is not committed to Git. Another host needs a SQLite backup transferred to it.

## Restart safety and recovery

Roster, start times, and battle records persist across restarts. Only the display
cache is lost. Full-synchronization SQLite transactions roll back incomplete
writes. Recovery snapshots are created after collection outside the checkout,
in `~/.local/state/wu-bot/gold-loot-backups/` under the runtime account.
`baseline.sqlite3` is preserved; `latest.sqlite3` is replaced atomically after an
integrity check. Custom databases use an adjacent `<filename>.backups` directory.

For recovery, stop the bot and watchers, preserve the damaged database and copy
latest.sqlite3 into its place with runtime-user ownership and mode 600. Verify
PRAGMA integrity_check before restarting. The original baseline backup preserves
the roster and start but may lack subsequent battles, whose recovery depends on
upstream retention. These backups share the disk and do not cover disk loss.

## Family-wide expansion

`/loot-leaderboard` ranks individual Clash accounts across the captured linked
clan rosters; it does not merge multiple accounts belonging to one Discord user.
Each row shows the captured clan and linked Discord account. The compact footer
shows the player and clan counts.

Run `tools/gold_loot.py expand-family` with the runtime interpreter to capture
all clans registered in the bot's clan collection, including CWL and untyped
clans. Every clan must load successfully before any roster changes are saved.
Existing players, start times and scores are preserved. Newly captured players
use the original session start time so available ClashKing history can be
backfilled on the next refresh. Duplicate player tags are inserted only once.

This remains a roster-snapshot test: future joiners and newly linked clans need
another `expand-family` run. Previously captured players and clans stay tracked,
including departures. Clan labels reflect the last captured roster. These totals
do not establish where a player was a member at the time of each attack.

A history refresh is limited to two minutes, retaining completed samples and
warning about unfinished players. The next refresh prioritizes older samples.
All saved battle records and backups remain durable across restarts.

## Discord account links

The displayed top 10 is resolved against both ClashPerk and ClashKing in
parallel. Matching owners are deduplicated and accounts known to either provider
are shown. Disagreeing owners show `Link conflict`, rather than selecting one.
An unavailable provider leaves successful results usable, while unmatched rows
say `Link unavailable` rather than claiming no account is linked. Gold scores
and clan membership do not depend on whether a Discord link exists.

Rows include the bot's existing Town Hall emoji, player name, gold looted,
player tag, linked Discord account and clan. The displayed players' current
Town Hall levels are fetched from the official API during refresh, in parallel
with Discord link resolution. An unavailable level shows `TH ?`; it never
changes the stored loot totals.
