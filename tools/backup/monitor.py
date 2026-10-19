"""Monitor existing systemd backup jobs; notify only on incidents/recovery."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
from uuid import UUID

from dotenv import dotenv_values
import requests

ROOT = Path(__file__).resolve().parents[2]
STATE = Path.home() / '.local/state/wu-backup'
CONFIG = Path.home() / '.config/wu-backup'
JOBS = {'cwl': ('cwl-backup', 20 * 60), 'mongo': ('cwl-mongo-backup', 45 * 60),
        'verification': ('cwl-backup-check', 30 * 3600)}


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def inspect_unit(name):
    result = subprocess.run(['systemctl', '--user', 'show', name, '--property=LoadState,ActiveState,Result,UnitFileState'],
                            capture_output=True, text=True, timeout=15, check=True)
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def issues(now, records, units, remote_enabled):
    found = []
    if not remote_enabled:
        found.append('R2 backup copying is disabled.')
    for kind, (unit, limit) in JOBS.items():
        timer = units.get(unit + '.timer', {})
        service = units.get(unit + '.service', {})
        if timer.get('ActiveState') != 'active' or timer.get('UnitFileState') != 'enabled':
            found.append(f'{kind}: backup timer is stopped or disabled.')
        if service.get('LoadState') != 'loaded':
            found.append(f'{kind}: backup service is missing.')
        elif service.get('Result', 'success') != 'success':
            found.append(f'{kind}: latest backup/check job failed.')
        for location in ('local', 'remote'):
            value = records.get(kind, {}).get(location + '_success')
            try:
                stamp = datetime.fromisoformat(value).timestamp()
                if not datetime.fromisoformat(value).tzinfo:
                    raise ValueError('Missing timezone')
            except (ValueError, TypeError, OverflowError):
                stamp = None
            if stamp is None or stamp > now + 300 or now - stamp > limit:
                found.append(f'{kind}: {location} backup/check is missing or overdue.')
    return sorted(found)


def retain_running_incidents(current, previous, units):
    """Starting a job resets systemd Result; that is not proof of recovery."""
    result = set(current)
    for kind, (unit, _) in JOBS.items():
        if units.get(unit + '.service', {}).get('ActiveState') in {'activating', 'active', 'deactivating'}:
            result.update(item for item in previous.get('issues', []) if item.startswith(kind + ':'))
    return sorted(result)


def deliver(current, previous, now, send):
    """Persist notification state only after delivery; failures retry next run."""
    old = previous.get('issues', [])
    if current == old and (not current or now - previous.get('notified_at', 0) < 6 * 3600):
        return previous
    if current:
        content = '**CWL backup needs attention**\n' + '\n'.join('- ' + item for item in current)
        content += '\nCheck the CWL backup services on the host. No live data has been restored or changed.'
    else:
        content = '**CWL backups recovered**\nAll monitored jobs, timers, and local/R2 freshness checks are healthy again.'
    send(content)
    return {'issues': current, 'notified_at': now}


def send_discord(content):
    config = dotenv_values(ROOT / '.local/cwl-backup-alerts.env')
    channel = str(config.get('CWL_BACKUP_ALERT_CHANNEL_ID', ''))
    if not channel.isdigit():
        raise RuntimeError('Backup alert channel is not configured')
    token = dotenv_values(ROOT / '.local/cwl-web.env').get('DISCORD_TOKEN')
    if not token:
        raise RuntimeError('Backup alert bot token is unavailable')
    # Existing bot identity, REST only: no second gateway session or bot process.
    response = requests.post(f'https://discord.com/api/v10/channels/{channel}/messages',
        headers={'Authorization': 'Bot ' + token},
        json={'content': content, 'allowed_mentions': {'parse': []}}, timeout=20)
    if response.status_code != 200:
        raise RuntimeError(f'Backup alert delivery failed (HTTP {response.status_code})')


def ping_external(url, healthy, get=requests.get):
    """Use Healthchecks' managed dead-man switch; never transmit logs or secrets."""
    if not url:
        return False
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'hc-ping.com'
            or parsed.query or parsed.fragment):
        raise RuntimeError('External heartbeat must be an HTTPS hc-ping.com UUID URL')
    try:
        check_id = str(UUID(parsed.path.strip('/')))
    except ValueError:
        raise RuntimeError('External heartbeat URL has an invalid check ID') from None
    endpoint = 'https://hc-ping.com/' + check_id + ('' if healthy else '/fail')
    try:
        response = get(endpoint, timeout=(5, 10), allow_redirects=False)
    except requests.RequestException:
        # Request errors include the private Ping URL; do not leak them to journal.
        raise RuntimeError('External heartbeat delivery failed') from None
    if response.status_code != 200:
        raise RuntimeError(f'External heartbeat rejected (HTTP {response.status_code})')
    return True


def main():
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Independent from backup lock so hung backups can be detected.
    with (STATE / 'monitor.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = time.time()
        records = {kind: read_json(STATE / (kind + '-status.json')) for kind in JOBS}
        path = STATE / 'monitor-notifications.json'
        previous = read_json(path)
        units = {}
        try:
            units = {unit + suffix: inspect_unit(unit + suffix) for unit, _ in JOBS.values()
                     for suffix in ('.timer', '.service')}
            current = issues(now, records, units, (CONFIG / 'r2-enabled').exists())
        except (OSError, subprocess.SubprocessError):
            current = ['Could not inspect backup services; monitoring needs attention.']
        current = retain_running_incidents(current, previous, units)
        report = STATE / 'monitor-health.json'
        temporary = report.with_suffix('.pending')
        temporary.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'issues': current}, indent=2))
        os.replace(temporary, report)
        # Make an unconfigured notification route visible even while healthy.
        configured = str(dotenv_values(ROOT / '.local/cwl-backup-alerts.env').get('CWL_BACKUP_ALERT_CHANNEL_ID') or '')
        external_url = str(dotenv_values(ROOT / '.local/cwl-backup-alerts.env').get('CWL_BACKUP_HEALTHCHECK_URL') or '').strip()
        if not configured.isdigit():
            ping_external(external_url, False)
            print('Monitoring checked; Discord notification destination is not configured', flush=True)
            return
        # Signal known failures even if Discord is unreachable. Healthy heartbeat
        # follows successful inspection and notification processing.
        external_error = None
        if current:
            try:
                ping_external(external_url, False)
            except RuntimeError as error:
                external_error = str(error)
        updated = deliver(current, previous, now, send_discord)
        if updated != previous:
            temporary = path.with_suffix('.pending')
            temporary.write_text(json.dumps(updated, indent=2))
            os.replace(temporary, path)
        if external_error:
            raise RuntimeError(external_error)
        if not current:
            ping_external(external_url, True)
        if not external_url:
            print('External outage monitoring pending Healthchecks Ping URL', flush=True)
        print('Backup monitoring: ' + ('attention needed' if current else 'healthy'), flush=True)


if __name__ == '__main__':
    main()
