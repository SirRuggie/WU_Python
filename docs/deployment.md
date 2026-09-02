# Deployment topology

None of this is discoverable from the repo — the systemd unit is not tracked and
the venv path is invisible from the code. Verified 2026-08-02.

## The box

Hetzner VPS:

| | |
|---|---|
| SSH | `wubot@178.156.187.236` |
| Hostname | `Arcane` |
| OS | Ubuntu |
| User | `wubot` (has sudo) |
| Repo | `/home/wubot/wu-bot`, branch `main` |
| Python | `/home/wubot/wu-bot/venv/bin/python` — 3.12.3 |
| Entrypoint | `main.py` |
| Service | `wu-bot.service`, enabled |

On 2026-08-02 the host reported that a restart was pending for a kernel update.
That is a dated observation, not proof that a restart is still pending. A host
restart will bounce the bot and should be scheduled deliberately.

## venv

`/home/wubot/wu-bot/venv` — and it is **not activated in a plain ssh session**.
Always call the interpreter or pip by explicit path:

```bash
/home/wubot/wu-bot/venv/bin/pip install <pkg>
```

Never hand back a bare `pip install` for this project; it will hit the system
Python and silently do nothing useful.

## systemd

Verified unit at `/etc/systemd/system/wu-bot.service`:

```ini
[Unit]
Description=WU Discord Bot
After=network.target

[Service]
Type=simple
User=wubot
WorkingDirectory=/home/wubot/wu-bot
Environment="PATH=/home/wubot/wu-bot/venv/bin"
ExecStart=/home/wubot/wu-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Drop-in at `/etc/systemd/system/wu-bot.service.d/override.conf`:

```ini
[Service]
Environment=PYTHONUNBUFFERED=1
```

- `Restart=always` is present. This is load-bearing: `reboot.py:170` calls
  `os._exit(0)` and depends entirely on that directive to come back up.
- `PYTHONUNBUFFERED=1` is set in a drop-in override, which is why logs appear
  promptly in `journalctl`.
- There is no `EnvironmentFile=` directive. Application configuration comes
  from `python-dotenv`, not systemd.

## Configuration

`.env` at `/home/wubot/wu-bot/.env`, loaded by `load_dotenv()` in `main.py`.
Appending to that file is the correct way to add an environment variable.
A service restart is required for the process to read a changed value.

Names present when inspected on 2026-08-02 (values deliberately omitted):

```text
DISCORD_TOKEN
MONGODB_URI
BAND_DEBUG
CLOUDINARY_API_KEY
CLOUDINARY_API_SECRET
CLASHKING_API_TOKEN
```

The two `CLOUDINARY_*` names are retired: since the September 2026 move to
Cloudflare R2 nothing reads them, and image uploads need the `R2_*` names in
[Cloudflare R2 (image uploads)](#cloudflare-r2-image-uploads) instead.

`CLASHKING_API_TOKEN` is the ClashKing developer bearer token used by `/todo`,
`/accounts`, Clash of Cards, LazyCWL, and clan-history expansion through
`POST /v2/links/shared`. The endpoint accepts up to 100 Discord IDs and player
tags per request, omits hidden links, and applies per-application usage tracking
and rate limits. Add the dashboard-issued token to `.env`, then restart the
service.

The Clash of Cards hub uses `CARDS_GUILD_ID`, set to the decimal Discord server
ID for Warriors United, and `CARDS_CHANNEL_ID`, set to the decimal Discord
channel ID for its family trade board. The feature fails closed when the guild
value is missing, invalid, or does not match the interaction guild; the rest of
the bot continues running. The channel is where proposal and status alerts are
published in addition to best-effort participant DMs. A channel-delivery
failure must not widen guild scope or discard the saved proposal.

Add both values to `.env` before deploying the card hub, then restart the
service so `python-dotenv` loads them. The configured channel should be inside
the configured guild, and the bot needs **View Channel**, **Send Messages**, and
**Read Message History** there so it can publish and update trade-board posts.

```text
CARDS_GUILD_ID=1078723854303756298
CARDS_CHANNEL_ID=<decimal Discord channel id>
```

The BAND iCal feature also reads `BAND_ICAL_SYNC1`, `BAND_ICAL_SYNC2`,
`BAND_ICAL_SYNC3`, `SYNC_DM_USER_IDS`, `SYNC_DM_OFFSETS`,
`SYNC_DM_ANNOUNCE_ON_DISCOVERY`, and `SYNC_DM_SUMMARY_FILTER`. Whether each is
currently populated is deployment state and must be checked on the host without
printing its value into chat or logs.

Some values in `.env` are credentials in a non-obvious way — the BAND iCal feed
URLs grant unauthenticated read access to the calendars. See
[band-ical-feeds.md](band-ical-feeds.md).

## Cloudflare R2 (image uploads)

Since September 2026 uploaded clan logos, banners and FWA base images live in
a Cloudflare R2 bucket instead of Cloudinary (why: [media-hosting.md](media-hosting.md)).
The bot needs five variables in `.env`. When any is missing, uploads fail
closed with a reply naming them and the rest of the bot runs as normal; the
boot log says `[WARN] R2 is not configured`.

```text
R2_ACCOUNT_ID=<Cloudflare account id>
R2_ACCESS_KEY_ID=<R2 API token access key>
R2_SECRET_ACCESS_KEY=<R2 API token secret>
R2_BUCKET=<bucket name>
R2_PUBLIC_BASE_URL=https://img.<your-domain>
R2_IMAGE_TRANSFORMS=true        # optional, step 4 below
```

One-time setup in the Cloudflare dashboard:

1. **R2 > Create bucket.** Any name; that name is `R2_BUCKET`.
2. **R2 > Manage API tokens > Create API token** with *Object Read & Write*
   scoped to that bucket. The access key and secret it shows once are
   `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY`; the account id is on the R2
   overview page.
3. **Bucket > Settings > Custom Domains > Connect domain**, for example
   `img.<your-domain>` on the zone already on Cloudflare. That hostname,
   with scheme and without a trailing slash, is `R2_PUBLIC_BASE_URL`. The
   managed `r2.dev` URL also works but is rate-limited and uncached;
   Cloudflare documents it as non-production.
4. Optional, recommended: **Images > Transformations > enable for the
   zone**, then set `R2_IMAGE_TRANSFORMS=true`. Every render then asks for a
   width-capped rendition (`/cdn-cgi/image/width=256,fit=scale-down,format=auto/…`)
   instead of the original. 5,000 unique transformations a month are free
   and this bot uses a few hundred. Leave the flag off until the zone toggle
   is on: with the flag on and transformations disabled, every image breaks.
   On an `r2.dev` base the flag is ignored automatically.

Objects are stored under content-hashed keys
(`clan_logos/Warriors_United/<Name>.<hash>.png`) with a one-year immutable
Cache-Control, so a replaced image always gets a new URL and no cache,
Cloudflare's or Discord's, can serve a stale one. Mongo holds the raw public
URL; `utils/media_urls.optimized()` builds the delivery URL at render time.

### Migrating the existing Cloudinary images

Rows still pointing at Cloudinary keep working: the bot rewrites those to
Cloudinary's size-capped renditions until they are moved. To move them, with
the `R2_*` values in `.env`:

```bash
cd /home/wubot/wu-bot
/home/wubot/wu-bot/venv/bin/python tools/migrate_media_to_r2.py --dry-run
/home/wubot/wu-bot/venv/bin/python tools/migrate_media_to_r2.py
```

The script downloads each original from Cloudinary, uploads it to the bucket
under the same folder and name, and `$set`s the new URL. It is idempotent,
skips rows already moved, and touches nothing on Cloudinary. Restart the
service afterwards so the FWA base maps reload from Mongo. Once `migrated=`
covers every row and the panels look right, the Cloudinary account can go and
`utils/cloudinary_urls.py` can be deleted (see its docstring).

## Database

**MongoDB is remote.** `mongod` is inactive on the box. Driver is pymongo
`AsyncMongoClient` (native async — *not* motor), configured in `utils/mongo.py`.

Collection handles are declared in `utils/mongo.py`, and several are commented
out — dead collections that may still hold data remotely.

⚠️ **That file is NOT a complete inventory.** `extensions/tasks/cwl_reminder.py`
accesses `mongo_client.database.cwl_reminder` and
`mongo_client.database.cwl_pending_reminders` at 10+ call sites (lines 258, 269,
275, 325, 342, 405, 422, 444, …). `AsyncMongoClient.__getattr__` returns a
*Database*, so `.database` is a second database **literally named `database`** —
not the `settings` database where `utils/mongo.py` declares
`cwl_pending_reminders`. Reads and writes there are self-consistent so nothing is
losing data, but the declared handle in `utils/mongo.py` is dead code and there
is a whole second database this file does not mention.

Anyone adding a collection needs to know which database they are landing in.

## Host baseline observed 2026-08-02

These numbers are comparison points, not current monitoring data:

- Service had been active for about three days, with 7 tasks.
- Bot memory was about 99 MB, with a 104.4 MB peak.
- Host had 1.9 GiB RAM, about 1.2 GiB available, and no swap.
- Disk was 38 GB total, 3.9 GB used (11%).
- The host timezone was UTC; clock synchronization and NTP were active.
- An error grep over the preceding hour returned zero lines.

Normal logs include the recruit-role cleanup every 30 minutes and hikari
gateway reconnect/resume messages. Those lines by themselves are not incidents.

Keep internal timestamps UTC-aware. Discord `<t:epoch:F>` timestamps perform
viewer-local display conversion.

## Operator command handoff

Ruggie, not Codex, performs deployments. These are commands to hand to the
operator when appropriate:

```bash
cd /home/wubot/wu-bot
git pull origin main
/home/wubot/wu-bot/venv/bin/pip install -r requirements.txt
sudo systemctl restart wu-bot
```

Useful read-only checks:

```bash
sudo systemctl status wu-bot
sudo systemctl cat wu-bot.service
sudo journalctl -u wu-bot -f --lines=60
sudo journalctl -u wu-bot --since "1 hour ago" | grep -i error
/home/wubot/wu-bot/venv/bin/python --version
```

After a restart, the historical scheduler check was:

```bash
sudo journalctl -u wu-bot --since "5 min ago" | grep -c "Scheduler initialized"
```

Treat a count as evidence only that the matching log line appeared; it does not
verify every scheduled job.

## Credential hygiene

- A sudo password for the public VPS was reportedly shared in a chat transcript
  on 2026-08-02. Rotation status is unknown; confirm that it was rotated. Never
  copy it into this repository or project knowledge.
- `extensions/commands/slap.py` still contains a Kawaii API token in source.
  Rotate it, move its replacement to `.env`, and remove it from source in a
  dedicated security change. Do not fold that into unrelated feature work.
- Prefer SSH key-only authentication and consider `fail2ban` for the public SSH
  endpoint.

## Corrections to the 2026-08-02 server reference

The original reference captured point-in-time facts that later became stale:

- The repository now pins `hikari==2.3.5` and
  `hikari-lightbulb==3.0.3`, not 2.3.3/3.0.1.
- `utils/mongo.py` uses pymongo's native async `AsyncMongoClient`; Mongo calls
  through it are not the synchronous pymongo calls described in the original
  note.
- `icalendar` is now in `requirements.txt` and the BAND iCal task exists. An old
  package inventory saying it was absent is not a current dependency verdict.
- The component dispatcher now has an error boundary and unknown-action guard.
  Its remaining defects, including missing authorization enforcement and the
  recruit-role pagination key bug, are tracked in
  [component-dispatcher.md](component-dispatcher.md).
- Repo cleanliness, installed package versions, service uptime, resource use,
  and pending-restart state were observations from 2026-08-02. Recheck them;
  never treat them as invariants.

## Deploys

**Ruggie deploys manually. Do not ssh to the box, do not `git pull` on it, and
do not restart the service.** Hand over commands to run rather than running
them.
