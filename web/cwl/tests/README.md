# Isolated card layout tests

Run from `web/cwl`:

```bash
NODE_PATH=/path/to/playwright/node_modules npm run test:layout
```

This host already has Playwright at `/tmp/wu-compare-tools/node_modules` and
Chrome at `/usr/bin/google-chrome`. Set `CHROME_PATH` for another installed Chrome
and `WU_TEST_PYTHON` for a Python environment with the repository backend test
dependencies (default: the repository `.venv/bin/python`). No package is installed
by this script. Vitest remains `npm test`.

The script builds the frontend, exports the committed backend into a temporary
directory, starts the repository-owned `fixtures/player_cards.py` on loopback
8952, runs Chrome checks, then stops the fixture. All database data is temporary;
the Python guard denies external connections and production/default service ports.
The browser permits only that fixture origin. The 125 accounts have 8–9-character
tags and player/clan names no longer than 15 characters.

Checks cover both card views at 320/360/700/701/1440px: metadata nowrap and single
text line, unchanged height for long tags, tag/lock not clipped, TH before the
name, no icon-column indent on lines 2–3, and no page overflow. At 360px the output
also reports both approved long-clan examples, whether the suffix fits, and its
available/required width. The original line-2 test is part of this command.

Fixture setup deliberately creates a publication in season 1 and a withdrawn
publication in season 3, and seeds signup-change audit examples. These are setup
writes to the temporary DB only. Layout checks do not review or change signups.
The dedicated review smoke may explicitly mark one item in season 1 and attempt
Mark all in season 4 with its second request failed; only review rows may change.
