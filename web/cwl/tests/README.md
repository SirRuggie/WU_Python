# Isolated card layout tests

From a clean repository checkout, inside `web/cwl`:

```bash
npm ci
npm run test:layout
```

Playwright is a locked devDependency; no external `NODE_PATH` is needed. The
runner uses installed Chrome (`/usr/bin/google-chrome` by default, or
`CHROME_PATH`). If Chrome is absent it prints an explicit `SKIP test:layout`
message. A skip is not a passed layout check.

The Python backend test environment is also required: use the repository
`.venv/bin/python`, or set `WU_TEST_PYTHON` to an existing environment with the
repository backend dependencies. The script installs no Python dependencies.

The frontend build and backend imports both use this checkout's **working tree**,
not a separate HEAD archive. For release evidence run from a clean checkout of
the tested SHA. The runner starts `fixtures/player_cards.py` on loopback 8952,
runs Chrome checks, and stops the fixture. Database data is temporary; the Python
network guard denies external connections and production/default service ports.
The browser permits only the fixture origin. Discord TH image requests are
fulfilled locally with a 64px stub, exercising the real image element without
external requests. Other external requests are blocked.

The 125 fixture accounts have 8–9-character tags and names no longer than 15
characters. Both card views are checked at 320/360/700/701/1440px: metadata nowrap,
long-tag height, unclipped tag/lock, loaded and unclipped TH image before the name,
no icon-column indent, and no page overflow. At 360px the output also measures the
approved long-clan examples and available/required suffix width.

Fixture setup creates a publication in season 1, a withdrawn publication in
season 3, and signup-change audit examples in a temporary database. Layout tests
do not review or change signups. Vitest remains `npm test`.
