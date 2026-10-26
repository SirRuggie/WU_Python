"""Repeatable validation gate for war reminders and their shared dependencies."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = [
    'tests/test_war_reminders.py',
    'tests/test_war_reminder_overview.py',
    'tests/test_cwl_web_war_reminders.py',
    'tests/test_war_reminder_store.py',
    'tests/test_war_reminder_worker_failures.py',
    'tests/test_war_reminder_architecture.py',
    'tests/test_account_links_service.py',
    'tests/test_cwl_dual_links.py',
    'tests/test_staff_link_owner.py',
    'tests/test_cwl_web_manage_clans.py',
    'tests/test_war_operations_ux.py',
    'tests/test_cwl_web_foundation.py',
    'tests/test_cwl_dashboard_state.py',
    'tests/test_official_clan_weights.py',
    'tests/test_clan_weight_trial.py',
]
COMMANDS = [
    [sys.executable, '-m', 'pytest', '-q', *BACKEND],
    ['npm', '--prefix', 'web/cwl', 'test', '--', 'src/warReminders/types.test.ts', 'src/warReminders/DeliveryHistory.test.tsx',
     'src/warReminderPreview.test.ts', 'src/clanManagement/ClanDirectory.test.tsx', 'src/clanManagement/reminderOverview.test.ts', 'src/ClanFilters.test.ts',
     'src/channelSearch.test.ts', 'src/DiscordPreview.test.tsx'],
    [str(ROOT / 'web/cwl/node_modules/.bin/tsc'), '-b', 'web/cwl/tsconfig.json'],
    ['git', 'diff', '--check'],
]

if __name__ == '__main__':
    for command in COMMANDS:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
    # The default Vite output may be served by a live dashboard on this host.
    # Validation must never replace production assets.
    with tempfile.TemporaryDirectory(prefix='wu-war-reminder-check-') as output:
        result = subprocess.run(
            ['npm', 'exec', '--', 'vite', 'build', '--outDir', output],
            cwd=ROOT / 'web/cwl', check=False,
        )
        if result.returncode:
            raise SystemExit(result.returncode)
    print('War reminder validation passed. Live delivery is a separate authorized check.')
