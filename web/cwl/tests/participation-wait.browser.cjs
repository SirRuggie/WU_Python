/* Actual App, detached read-only API states. No Clash/Discord requests. */
const { createServer } = require("node:http"),
  fs = require("node:fs"),
  path = require("node:path"),
  assert = require("node:assert/strict");
const { chromium } = require("playwright");
function apiData(pathname, mode) {
  const complete = mode === "complete";
  const warning = {
    waiting: "November CWL hasn't started in Clash yet",
    later: "Clash reports a later CWL month than the selected month",
    partial: "CWL observations are incomplete",
    unavailable: "Some Clash CWL data could not be refreshed",
    complete: null,
  }[mode];
  if (pathname.endsWith("/auth/me"))
    return {
      authenticated: true,
      user: { id: "123456789012345678", username: "Fixture staff" },
      is_owner: true,
      can_edit: true,
      csrf_token: "fixture",
    };
  if (pathname.endsWith("/config")) return { dev_fixture: true };
  if (pathname.endsWith("/seasons"))
    return {
      seasons: [
        { id: 1, label: "November 2026", status: "draft", signup_open: true },
      ],
      member_season: { season_id: 1, revision: 0 },
    };
  if (pathname.endsWith("/participation"))
    return {
      publication_version: 1,
      accounts: Array.from({ length: 170 }, (_, i) => ({
        tag: "#P" + i,
        player_name: "Fixture member " + String(i + 1).padStart(3, "0"),
        user_id: null,
        town_hall: 16,
        pool: "main",
        assigned_clan_tag: "#C2Y",
        assigned_clan_name: "Fixture clan",
        attacks: complete ? 7 : null,
        stars: complete ? 21 : null,
        notes: "",
        revision: 0,
        updated_by: null,
        updated_at: null,
        in_latest_publication: true,
        source_attacks: complete ? 7 : null,
        source_stars: complete ? 21 : null,
        source_status: complete
          ? "complete"
          : mode === "partial"
            ? "partial"
            : "unavailable",
        source_complete: complete,
        source_warning: null,
      })),
      sync: {
        cycle: "2026-11",
        cycle_source: "settings",
        enabled: true,
        status: mode === "later" ? "season_mismatch" : mode,
        warning,
        last_checked_at: "2026-11-01T12:00:00Z",
        last_success_at: complete ? "2026-11-01T12:00:00Z" : null,
        updated_at: "2026-11-01T12:00:00Z",
      },
    };
  return {
    items: [],
    accounts: [],
    members: [],
    entries: [],
    signups: [],
    options: [],
    unread_count: 0,
  };
}
module.exports = { apiData };
async function run() {
  const dist = path.resolve(__dirname, "../dist"),
    output = process.env.WU_PARTICIPATION_WAIT_OUTPUT;
  assert(output, "Explicit owned output directory required");
  fs.mkdirSync(output, { recursive: true });
  const server = createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    let file = path.resolve(dist, "." + url.pathname);
    if (
      !file.startsWith(dist + path.sep) ||
      !fs.existsSync(file) ||
      fs.statSync(file).isDirectory()
    )
      file = path.join(dist, "index.html");
    res.setHeader(
      "Content-Type",
      file.endsWith(".js")
        ? "text/javascript"
        : file.endsWith(".css")
          ? "text/css"
          : "text/html",
    );
    res.end(fs.readFileSync(file));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const evidence = [];
  try {
    for (const width of [320, 360, 390, 1440])
      for (const mode of [
        "waiting",
        "later",
        "partial",
        "unavailable",
        "complete",
      ]) {
        const page = await browser.newPage({
            viewport: { width, height: 900 },
          }),
          errors = [],
          requests = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("**/*", async (route) => {
          const request = route.request(),
            url = new URL(request.url());
          if (url.origin !== origin) return route.abort();
          if (!url.pathname.startsWith("/api/")) return route.continue();
          assert.equal(
            request.method(),
            "GET",
            "Wording checks must remain read-only",
          );
          requests.push(url.pathname);
          await route.fulfill({
            contentType: "application/json",
            body: JSON.stringify(apiData(url.pathname, mode)),
          });
        });
        await page.goto(origin + "/cwl/results?season=1");
        await page.locator(".participation-capture").waitFor();
        await page.locator(".participation-row").first().waitFor();
        const text = await page.locator(".participation-capture").innerText();
        if (mode === "waiting") {
          assert.equal(
            text.split("November CWL hasn't started in Clash yet").length - 1,
            1,
          );
          assert(!text.includes("CWL month mismatch"));
          assert(!text.includes("incomplete, stale or unavailable"));
          assert.equal(
            await page.locator('.participation-capture [role="alert"]').count(),
            0,
          );
        } else {
          assert(!text.includes("hasn't started in Clash yet"));
          if (mode === "later") assert(text.includes("later CWL month"));
          if (mode !== "complete")
            assert(
              text.includes(
                "170 accounts with incomplete, stale or unavailable source results.",
              ),
            );
        }
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        );
        assert.deepEqual(errors, []);
        assert(
          !requests.some((url) => url.includes("/history")),
          "Closed history must not fetch",
        );
        await page.screenshot({
          path: path.join(output, `${width}-${mode}.png`),
          fullPage: false,
        });
        evidence.push({
          width,
          mode,
          noOverflow: true,
          requests,
          pageErrors: errors,
        });
        await page.close();
      }
    fs.writeFileSync(
      path.join(output, "evidence.json"),
      JSON.stringify(evidence, null, 2),
    );
    console.log(JSON.stringify(evidence));
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}
if (require.main === module)
  run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
