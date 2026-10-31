"""Owner visitor summary with isolated, synthetic daily counts."""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(Path(__file__).resolve().parent))
import staff_nav
from aiohttp import web
from utils.dashboard_visit_store import LOCAL_TIMEZONE
app = staff_nav.app
now = datetime.now(timezone.utc)
for offset in range(30):
    at = now - timedelta(days=offset)
    for person in range(1, 4 + offset % 7):
        app['visit_store'].record(str(700000000000000000 + person),
                                 day=at.astimezone(LOCAL_TIMEZONE).date(),
                                 at=at, is_staff=person <= 2)
if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=staff_nav.fixture.PORT)
