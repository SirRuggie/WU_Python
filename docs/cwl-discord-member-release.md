# Operator release: Discord CWL member flow

This is an operator handoff, not a deployment record. Automatic approval review
rejected production pull/restart actions under the manual-deployment instruction
in `docs/deployment.md`. Do not run these steps until that block is resolved.
The user's deployment request is recorded; no production change was made by this
review. Do not use the historical Arcane SSH host.

The coordinating task verified these current local services:

- Dashboard: user `wu-cwl-demo-web.service`, working directory
  `/nvme0n1-disk/Projects/Bot - Warriors United`, private environment
  `.local/cwl-web.env`, loopback port `8766`.
- Bot: system `wu-bot.service`, user `botrunner`, working directory
  `/home/botrunner/wu-bot`, private environment `.env`.

Recheck these paths and the units before running commands. Do not print either
private environment or `systemctl show ... Environment` into logs.

## Integrate the reviewed branch

From the isolated builder worktree, publish the feature branch (not main):

```bash
git push origin codex/cwl-discord-member
```

From the dashboard checkout on the production machine, require a clean checkout
and fast-forward only. Stop on any conflict, dirty checkout, or divergence; bring
newer main changes into the feature and rerun tests before release.

```bash
cd '/nvme0n1-disk/Projects/Bot - Warriors United'
test -z "$(git status --porcelain)" || exit 1
test "$(git branch --show-current)" = main || exit 1
git fetch origin
git merge --ff-only origin/main
git merge --ff-only origin/codex/cwl-discord-member
git push origin main
release_revision=$(git rev-parse HEAD)
sudo -u botrunner git -C /home/botrunner/wu-bot fetch origin
test -z "$(sudo -u botrunner git -C /home/botrunner/wu-bot status --porcelain)" || exit 1
test "$(sudo -u botrunner git -C /home/botrunner/wu-bot branch --show-current)" = main || exit 1
sudo -u botrunner git -C /home/botrunner/wu-bot merge --ff-only origin/main
test "$(sudo -u botrunner git -C /home/botrunner/wu-bot rev-parse HEAD)" = "$release_revision" || exit 1
```

## Configure the private bridge

The following operator-only Python creates one random secret in memory, backs up
both environment files with their original ownership/permissions, and atomically
updates only the bridge keys. It never prints the secret. Existing provider,
OAuth, database and backup configuration remains intact. Keep the two timestamped
backups until health verification succeeds. Do not run this with shell tracing.

```bash
sudo python3 - <<'PY'
import datetime, os, pathlib, re, secrets, tempfile
web = pathlib.Path('/nvme0n1-disk/Projects/Bot - Warriors United/.local/cwl-web.env')
bot = pathlib.Path('/home/botrunner/wu-bot/.env')
secret = secrets.token_urlsafe(48)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
originals = [(path, path.stat(), path.read_text()) for path in (web, bot)]
for path, stat, text in originals:
    backup = path.with_name(path.name + '.before-cwl-member-' + stamp)
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(text)
    os.chown(backup, stat.st_uid, stat.st_gid)
    os.chmod(backup, 0o600)
for path, stat, text in originals:
    updates = {'CWL_DISCORD_BRIDGE_SECRET': secret}
    if path == bot:
        updates['CWL_DISCORD_BRIDGE_URL'] = 'http://127.0.0.1:8766'
    lines = [line for line in text.splitlines()
             if not any(re.match(r'^\s*(?:export\s+)?' + key + r'\s*=', line)
                        for key in updates)]
    lines.extend(key + '=' + value for key, value in updates.items())
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.cwl-bridge-')
    try:
        with os.fdopen(fd, 'w') as out:
            out.write('\n'.join(lines) + '\n')
            out.flush()
            os.fsync(out.fileno())
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
print('Bridge settings written; secret omitted.')
PY
```

If configuration fails midway, restore both timestamped backups before restarting.
Both processes must have the same secret. The dashboard also needs its existing
`DISCORD_TOKEN`. Protect the bridge path from public proxy access; local peer and
secret checks remain enforced by the application. No schema/data migration runs.

## Start and verify

```bash
cd '/nvme0n1-disk/Projects/Bot - Warriors United'
.venv/bin/python -c 'import cwl_web.discord_member, utils.cwl_member_service'
sudo -u botrunner /home/botrunner/wu-bot/venv/bin/python -c 'import os; os.chdir("/home/botrunner/wu-bot"); import extensions.commands.cwl_member'
systemctl --user restart wu-cwl-demo-web.service
systemctl --user is-active --quiet wu-cwl-demo-web.service || exit 1
curl --fail --silent http://127.0.0.1:8766/api/cwl/config >/dev/null || exit 1
sudo systemctl restart wu-bot.service
sudo systemctl is-active --quiet wu-bot.service || exit 1
systemctl --user show wu-cwl-demo-web.service -p ActiveEnterTimestamp -p NRestarts
sudo systemctl show wu-bot.service -p ActiveEnterTimestamp -p NRestarts
```

Inspect startup logs locally for successful Mongo restoration/lease, imports and
Discord command sync; do not publish logs containing private values. Verify both
HEADs and origin/main equal the intended release revision. Check the public
`https://dash.warriorsunited.cc/signup` response and its referenced hashed assets.
This change has no frontend source changes; do not replace newer served assets.

Use Discord's read-only application-command list to verify `cwl-member` exists
and has no administrator-only default permissions, or inspect the command picker
without invoking a save. Opening `/cwl-member` must remain private and write-free.
Do not send test messages or mutate member signups without an authorized test
recipient/destination. Isolated tests do not establish live delivery or physical
mobile rendering.
