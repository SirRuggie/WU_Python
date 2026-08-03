# Deployment topology

None of this is discoverable from the repo — the systemd unit is not tracked and
the venv path is invisible from the code. Verified 2026-08-02.

## The box

Hetzner VPS, `wubot@178.156.187.236`, working directory `/home/wubot/wu-bot`.

## venv

`/home/wubot/wu-bot/venv` — and it is **not activated in a plain ssh session**.
Always call the interpreter or pip by explicit path:

```bash
/home/wubot/wu-bot/venv/bin/pip install <pkg>
```

Never hand back a bare `pip install` for this project; it will hit the system
Python and silently do nothing useful.

## systemd

`wu-bot.service`:

- `Restart=always` is present. This is load-bearing: `reboot.py:170` calls
  `os._exit(0)` and depends entirely on that directive to come back up.
- `PYTHONUNBUFFERED=1` is set in a drop-in override, which is why logs appear
  promptly in `journalctl`.

## Configuration

`.env` at `/home/wubot/wu-bot/.env`, loaded by `load_dotenv()` in `main.py`.
Appending to that file is the correct way to add an environment variable.

Some values in `.env` are credentials in a non-obvious way — the BAND iCal feed
URLs grant unauthenticated read access to the calendars. See
[band-ical-feeds.md](band-ical-feeds.md).

## Database

**MongoDB is remote.** `mongod` is inactive on the box. Driver is pymongo
`AsyncMongoClient` (native async — *not* motor), configured in `utils/mongo.py`.

A consequence worth remembering: every collection handle is declared in
`utils/mongo.py`, so that file is the fastest inventory of what the bot stores.
Several handles there are commented out — dead collections that may still hold
data remotely.

## Deploys

**Ruggie deploys manually. Do not ssh to the box, do not `git pull` on it, and
do not restart the service.** Hand over commands to run rather than running
them.
