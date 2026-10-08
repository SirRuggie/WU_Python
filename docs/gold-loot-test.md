# Gold loot console test

Run from the repository with the existing `.env` / `COC_API_TOKEN`:

```bash
.venv/bin/python tools/gold_loot.py start
.venv/bin/python tools/gold_loot.py refresh
.venv/bin/python tools/gold_loot.py show
.venv/bin/python tools/gold_loot.py watch
```

`start` captures Warriors United (`#2YRVY8YCP`) members and each player's
**Gold Grab** achievement value. It refuses to overwrite an existing test.
Every player must be fetched successfully to create the test. Each player
has its own capture timestamp. The API is polled, not a realtime feed: the
starting boundary is the first returned counter for that player.

`refresh` fetches new counters and displays the top 10 increases. `show` displays
saved results without network access. `watch` refreshes every five minutes;
use `--interval 60` for one minute. Stop with Ctrl+C. Sample timestamps and
failed-refresh warnings identify stale results.

Data persists in `.local/gold-loot.sqlite3`. Use `--db /path/to/another.sqlite3`
on each command for a separate test. Run commands on the machine holding
this file; this prototype does not sync between local and server machines.

The test follows the **fixed starting roster**, including players who later
leave, and does not add later joiners. It measures subsequent Gold Grab
progress for those accounts, not only attacks made while in the clan.
It does not measure collectors, purchases, storage balance, or every reward
source. Ties use player tags for stable ordering. There are no Discord posts.

Counter subtraction avoids double counting and catches up after the watcher
stops. A decreased or missing counter leaves the last good sample unchanged.
No background service is installed: keep `watch` open for automatic refreshes,
or run `refresh` whenever you want the latest standings.

## Discord leaderboard

Run **`/loot-leaderboard`** in Warriors United. It refreshes the saved test and
shows a public goldenrod Components V2 panel with the top 10, gold gained,
test start time, and linked Discord accounts. The Update button refreshes the
same message, including account links, and bypasses the normal cache. Concurrent requests share a refresh;
results are cached for up to 60 seconds. API failures display saved totals with
a warning. The command never starts or resets a baseline.

The extension is discovered automatically at bot startup and registered only
in Warriors United. Restart the bot after deploying the code to register it.
The bot must have the existing `.local/gold-loot.sqlite3` file on its host;
when deploying to a different host, transfer a SQLite backup of that file to
preserve the original start time. Do not run `start` to replace this test.
The console and Discord command use the same shared tracker in
`utils/gold_loot.py`. No separate watcher is needed for command-driven refreshes.


## Restart safety and recovery

The baseline, roster, and samples persist in SQLite, not in the Discord cache.
A bot restart clears only the 60-second display cache. The next refresh computes
lifetime Gold Grab minus the same original baseline, catching up over downtime.
Writes use a transaction with full SQLite synchronization; incomplete writes
roll back. Refreshes never reset the baseline.

After each successful collection, the production default database is backed up
outside the checkout to `~/.local/state/wu-bot/gold-loot-backups/` (under the
botrunner account). `baseline.sqlite3` is kept unchanged; `latest.sqlite3` is
replaced atomically with an integrity-checked SQLite snapshot. Custom `--db`
paths use an adjacent `<database filename>.backups/` directory.

For recovery, stop the bot and any console watcher, preserve the damaged file,
and copy `latest.sqlite3` to `.local/gold-loot.sqlite3`, owned by botrunner with
mode 600. Verify `PRAGMA integrity_check` before restarting. If necessary use
`baseline.sqlite3`; refreshing catches up totals from the original baseline.
Never run `start` as recovery. These backups protect against loss of the working
file or checkout, but are on the same host: they do not cover loss of its disk.
