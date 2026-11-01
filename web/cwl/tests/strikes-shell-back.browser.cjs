/* Actual App shell + isolated read-only API fixtures; no production transport. */
const { createServer } = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const dist = path.resolve(__dirname, "../dist");
const output =
  process.env.WU_STRIKES_SHELL_OUTPUT || "/tmp/wu-strikes-shell-back";
fs.mkdirSync(output, { recursive: true });
const account = {
  player_tag: "#PYY",
  player_name: "Fixture member",
  current_clan_tag: "#PQQ",
  current_clan_name: "Fixture family",
  active_strikes: 0,
  total_strikes: 0,
  marked_for_replacement: false,
  status: "active",
  town_hall: 16,
  weight: 149000,
  quiet_days: 20,
  last_seen_at: "2026-10-01T00:00:00Z",
  observed_wars: 14,
  attacked_wars: 0,
  no_attack_wars: 14,
  observed_raid_weekends: 2,
  attacked_raid_weekends: 0,
  skipped_raid_weekends: 2,
  missed_attacks: 28,
  observed_attacks: 28,
};
const server = createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  let file = path.resolve(dist, "." + url.pathname);
  if (!file.startsWith(dist + path.sep)) file = path.join(dist, "index.html");
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory())
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
(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const evidence = [];
  try {
    for (const width of [360, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width === 360 ? 800 : 1000 },
      });
      const errors = [];
      const reads = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.route("**/*", async (route) => {
        const req = route.request(),
          url = new URL(req.url());
        if (url.origin !== origin) return route.abort();
        if (!url.pathname.startsWith("/api/")) return route.continue();
        assert.equal(
          req.method(),
          "GET",
          "Shell Back check must stay read-only",
        );
        reads.push(url.pathname + url.search);
        let data = {
          items: [],
          accounts: [],
          members: [],
          entries: [],
          signups: [],
          unread_count: 0,
        };
        if (url.pathname.endsWith("/auth/me"))
          data = {
            authenticated: true,
            user: { id: "123456789012345678", username: "Fixture" },
            is_owner: false,
            can_edit: true,
            dashboard_permissions: ["strikes", "strikes_add", "strikes_remove"],
            csrf_token: "fixture",
          };
        else if (url.pathname.endsWith("/config")) data = { dev_fixture: true };
        else if (url.pathname.endsWith("/seasons"))
          data = {
            seasons: [],
            member_season: { season_id: null, revision: 0 },
          };
        else if (url.pathname.endsWith("/strikes/accounts"))
          data = {
            accounts: [account],
            clans: [{ tag: "#PQQ", name: "Fixture family" }],
            total: 1,
          };
        else if (url.pathname.endsWith("/strikes/overview"))
          data = { entries: [], total: 0, summary: {}, clans: [], streak: {} };
        else if (url.pathname.endsWith("/strikes/tracking"))
          data = { clans: [] };
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(data),
        });
      });
      await page.goto(origin + "/strikes?activity_view=all&q=Fixture");
      await page.locator("[data-strike-player]").first().waitFor();
      await page.getByRole("button", { name: "Filters", exact: true }).click();
      await page.getByRole("dialog").waitFor();
      await page.goBack();
      await page.waitForFunction(() => !document.querySelector("dialog[open]"));
      assert(new URL(page.url()).searchParams.get("q") === "Fixture");
      await page.locator("[data-strike-player]").first().click();
      await page.getByText("Activity details", { exact: true }).waitFor();
      const detailUrl = page.url();
      await page.goBack();
      await page.locator("[data-strike-player]").first().waitFor();
      assert(new URL(page.url()).searchParams.get("q") === "Fixture");
      await page.goForward();
      await page.getByText("Activity details", { exact: true }).waitFor();
      await page.goto(detailUrl);
      await page.getByText("Activity details", { exact: true }).click();
      await page
        .getByText("Attacked in 0 of 14 known wars", { exact: true })
        .waitFor();
      assert(
        reads.some(
          (r) =>
            r.includes("/strikes/accounts?query=") &&
            r.includes("activity=true"),
        ),
      );
      assert.deepEqual(errors, []);
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await page.screenshot({
        path: path.join(output, `${width}-shell-back.png`),
        fullPage: false,
      });
      evidence.push({
        width,
        backRestoredFilters: true,
        directLinkActivity: true,
        pageErrors: errors,
        reads: reads.filter((r) => r.includes("/strikes/accounts")),
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
})().catch((error) => {
  console.error(error);
  server.close();
  process.exitCode = 1;
});
