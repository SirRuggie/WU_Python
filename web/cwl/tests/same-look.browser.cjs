/* Same isolated fixture/server contract as less-on-top; no live I/O. */
const { chromium } = require("playwright"),
  fs = require("node:fs"),
  path = require("node:path"),
  assert = require("node:assert/strict");
const output = process.env.WU_LAYOUT_OUTPUT,
  staff = process.env.WU_LESS_STAFF_URL,
  member = process.env.WU_LESS_MEMBER_URL;
for (const base of [staff, member]) {
  const url = new URL(base);
  assert.equal(url.hostname, "127.0.0.1");
  assert(![8766, 8767].includes(Number(url.port)));
}
const pages = [
  ["build", "/cwl/roster?season=1", "Build roster", staff],
  ["finalize", "/cwl/publish?season=1&step=review", "Finalize roster", staff],
  [
    "announcements",
    "/cwl/publish?season=1&step=announce",
    "Announcements",
    staff,
  ],
  ["declaration", "/cwl/readiness?season=1", "Declaration check", staff],
  ["results", "/cwl/results?season=1", "Results & participation", staff],
  ["bonus", "/cwl/bonuses?season=1", "Bonus medals", staff],
  ["exports", "/cwl/exports?season=1", "Exports", staff],
  ["seasons", "/cwl/settings?season=1", "Seasons", staff],
  ["reminders", "/cwl/reminders/signup?season=1", "Signup reminders", staff],
  ["tasks", "/tasks", "Tasks", member],
  ["signup", "/signup", "Sign up", member],
  ["saved", "/my-signups", "My signups", member],
  ["assignments", "/assignments", "My clan assignments", member],
];
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const cases = [],
    writes = [],
    errors = [];
  try {
    for (const width of [360, 1440])
      for (const [name, route, title, base] of pages) {
        const context = await browser.newContext({
          viewport: { width, height: width === 1440 ? 1000 : 800 },
        });
        await context.addInitScript(() =>
          localStorage.setItem(
            "wu-member-tour-v1",
            JSON.stringify({ skips: 3, dismissed: true }),
          ),
        );
        const page = await context.newPage();
        page.on("pageerror", (e) =>
          errors.push({ name, width, error: String(e) }),
        );
        page.on("request", (req) => {
          if (
            !["GET", "HEAD"].includes(req.method()) &&
            !req.url().endsWith("/dev/login")
          )
            writes.push({ name, width, path: new URL(req.url()).pathname });
        });
        await page.route("**/*", (route) => {
          const request = route.request(),
            url = new URL(request.url());
          if (url.origin !== base) return route.abort();
          if (request.method() !== "GET") return route.continue();
          const accounts = [
            "Aurora 032",
            "Ace",
            "Blaze",
            "Cinder",
            "Delta",
          ].map((name, i) => ({
            tag: [
              "#P222222Y",
              "#Q222222Y",
              "#G222222Y",
              "#L222222Y",
              "#R222222Y",
            ][i],
            name,
            town_hall: 18,
            current_clan_tag: "#R222222Y",
            current_clan_name: "Fixture Family",
            current_clan_type: i === 2 ? "FWA" : "CWL",
            verified: true,
            lazy_eligible: true,
            lazy_ineligible_reason: null,
            family_clan_status: "approved",
          }));
          if (url.pathname === "/api/cwl/linked-accounts")
            return route.fulfill({
              json: {
                accounts,
                updating: false,
                total: accounts.length,
                error: null,
                link_instruction: "Local sample",
              },
            });
          if (url.pathname === "/api/cwl/todo") {
            const now = Math.floor(Date.now() / 1000),
              row = {
                tag: accounts[0].tag,
                name: accounts[0].name,
                town_hall: 18,
                clan_tag: "#R222222Y",
                clan_name: "Fixture Family",
                used: 1,
                total: 2,
                remaining: 1,
                starts_at: now - 3600,
                ends_at: now + 3600,
                state: "inWar",
                detail: "Local sample attack remaining",
                fwa_outcome: {
                  status: "win",
                  opponent: "Local sample opponent",
                },
              };
            const views = Object.fromEntries(
              ["war", "cwl", "raid", "games", "private"].map((kind) => [
                kind,
                {
                  ok: true,
                  note: "Local sample",
                  notes: [],
                  unavailable: "",
                  incomplete: "",
                  loading: false,
                  rows: kind === "war" ? [row] : [],
                },
              ]),
            );
            return route.fulfill({
              json: {
                updating: false,
                snapshot: {
                  linked_account_count: accounts.length,
                  checked_at: new Date().toISOString(),
                  accounts,
                  views,
                },
              },
            });
          }
          if (url.pathname.endsWith("/manage-reminders"))
            return route.fulfill({
              json: {
                cycle: "2026-11",
                generation: "local",
                worker_ready: false,
                activated: false,
                campaign: {
                  timezone: "UTC",
                  paused: true,
                  signup_deadline: { at: "2026-11-20T17:00:00Z" },
                  reminder_sequence: { enabled: false },
                  messages: {},
                },
                schedule: [],
                signup_open: true,
                history: [],
                deliveries: [],
              },
            });
          return route.continue();
        });
        const setup = await page.request.get(
          base + "/qa/less-on-top/setup?count=125&mode=open",
        );
        assert.equal(setup.status(), 200);
        await page.request.post(base + "/api/cwl/dev/login");
        await page.goto(base + route);
        await page
          .getByRole("heading", { name: title, exact: true, level: 1 })
          .waitFor();
        await page.waitForLoadState("networkidle");
        await page
          .getByText("Checking linked accounts…", { exact: true })
          .waitFor({ state: "hidden", timeout: 15000 });
        await page
          .getByText("Loading linked accounts…", { exact: true })
          .waitFor({ state: "hidden", timeout: 15000 });
        if (name === "tasks") await page.locator(".todo-tabs").waitFor();
        if (name === "reminders")
          await page
            .getByText("Working…", { exact: true })
            .waitFor({ state: "hidden", timeout: 15000 });
        await page.evaluate(() => scrollTo(0, 0));
        const metrics = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth > innerWidth,
          headers: document.querySelectorAll("h1").length,
          headerHeight:
            document.querySelector(".cwl-page-header")?.getBoundingClientRect()
              .height ?? null,
          fonts: [...document.querySelectorAll(".cwl-page-header h1")].map(
            (e) => getComputedStyle(e).fontSize,
          ),
          headerRow: (() => {
            const header = document.querySelector(".cwl-page-header"),
              menu = header?.querySelector(
                ".roster-menu, .cwl-page-header-season",
              );
            if (!menu) return null;
            const title = header.querySelector("h1").getBoundingClientRect(),
              control = menu.getBoundingClientRect();
            return {
              display: getComputedStyle(header).display,
              overlap: title.top < control.bottom && control.top < title.bottom,
              height: header.getBoundingClientRect().height,
              seasonLeft: control.left,
              seasonWidth: control.width,
              seasonFont: getComputedStyle(
                menu.querySelector(".roster-menu-current") || menu,
              ).fontSize,
              seasonRight: control.right,
              headerRight: header.getBoundingClientRect().right,
            };
          })(),
        }));
        assert(!metrics.overflow, JSON.stringify({ name, width, metrics }));
        assert.equal(metrics.headers, 1);
        if (
          (process.env.WU_LAYOUT_PHASE || "candidate") !== "before" &&
          metrics.headerHeight !== null
        )
          assert(
            Math.abs(metrics.headerHeight - 44) < 1,
            JSON.stringify({ name, width, metrics }),
          );
        if ((process.env.WU_LAYOUT_PHASE || "candidate") !== "before")
          for (const font of metrics.fonts)
            assert.equal(
              font,
              width === 360 ? "20px" : "24px",
              JSON.stringify({ name, width, metrics }),
            );
        if (
          (process.env.WU_LAYOUT_PHASE || "candidate") !== "before" &&
          metrics.headerRow
        ) {
          assert.equal(
            metrics.headerRow.display,
            "flex",
            JSON.stringify({ name, width, metrics }),
          );
          assert(
            metrics.headerRow.overlap,
            JSON.stringify({ name, width, metrics }),
          );
          assert(
            Math.abs(metrics.headerRow.height - 44) < 1,
            JSON.stringify({ name, width, metrics }),
          );
          assert(
            Math.abs(
              metrics.headerRow.seasonRight - metrics.headerRow.headerRight,
            ) < 1,
            JSON.stringify({ name, width, metrics }),
          );
          assert(
            Math.abs(
              metrics.headerRow.seasonWidth - (width === 360 ? 152 : 200),
            ) < 1,
            JSON.stringify({ name, width, metrics }),
          );
          assert.equal(
            metrics.headerRow.seasonFont,
            "12px",
            JSON.stringify({ name, width, metrics }),
          );
        }
        await page.screenshot({
          path: path.join(output, `${name}-${width}.png`),
          fullPage: true,
        });
        cases.push({ name, width, ...metrics });
        if (name === "signup" || name === "saved") {
          let image;
          if (name === "signup") {
            await page
              .locator(".pool-choice-grid button")
              .filter({ hasText: "Main CWL" })
              .click();
            const card = page
              .locator(".account-list .account-card")
              .filter({ hasText: "Blaze" });
            await card.getByRole("checkbox").click();
            await page
              .getByRole("heading", {
                name: "Nuh uh uh, your account is in FWA!",
                exact: true,
              })
              .waitFor();
            assert.equal(await card.getByRole("checkbox").isChecked(), false);
            image = page.locator(".fwa-signup-animation");
          } else {
            await page
              .locator(".saved-signup-card")
              .first()
              .getByRole("button", { name: "Change CWL pool", exact: true })
              .click();
            image = page.locator(".pool-change-animation");
          }
          await image.waitFor({ state: "visible" });
          await page.screenshot({
            path: path.join(output, `${name}-dialog-${width}.png`),
            fullPage: true,
          });
          await page.emulateMedia({ reducedMotion: "reduce" });
          const reducedVisible = await image.isVisible();
          if ((process.env.WU_LAYOUT_PHASE || "candidate") !== "before")
            assert.equal(reducedVisible, false);
          await page.screenshot({
            path: path.join(output, `${name}-dialog-reduced-${width}.png`),
            fullPage: true,
          });
          cases.push({
            name: name + "-motion-dialog",
            width,
            reducedVisible,
            unsubmitted: true,
          });
          await page
            .getByRole("button", {
              name: name === "signup" ? "Got it" : "Cancel",
              exact: true,
            })
            .click();
        }
        await context.close();
      }
    assert.equal(cases.length, 30);
    if ((process.env.WU_LAYOUT_PHASE || "candidate") !== "before")
      for (const width of [360, 1440]) {
        const positions = cases
          .filter((item) => item.width === width && item.headerRow)
          .map((item) => item.headerRow.seasonRight);
        assert(positions.length >= 10);
        assert(
          Math.max(...positions) - Math.min(...positions) < 1,
          JSON.stringify({ width, positions }),
        );
      }
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(output, "results.json"),
      JSON.stringify(
        {
          phase: process.env.WU_LAYOUT_PHASE || "candidate",
          cases,
          writes,
          errors,
        },
        null,
        2,
      ),
    );
    console.log(JSON.stringify({ cases: cases.length, writes, errors }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
