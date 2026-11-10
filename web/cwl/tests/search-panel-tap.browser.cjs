/* Actual App shell + read-only API fixtures: a phone tap on a search-panel option must select it. */
const { createServer } = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const dist = path.resolve(__dirname, "../dist");
const account = (tag, name, clanTag, clanName, weight, id, discord) => ({
  player_tag: tag,
  player_name: name,
  current_clan_tag: clanTag,
  current_clan_name: clanName,
  active_strikes: 3,
  total_strikes: 3,
  marked_for_replacement: true,
  status: "risk",
  town_hall: 14,
  weight,
  quiet_days: 2,
  last_seen_at: "2026-11-01T12:00:00Z",
  observed_wars: 3,
  attacked_wars: 3,
  no_attack_wars: 0,
  observed_raid_weekends: 0,
  attacked_raid_weekends: 0,
  skipped_raid_weekends: 0,
  missed_attacks: 0,
  observed_attacks: 0,
  discord_id: id,
  discord_name: discord,
});
const accounts = [
  account(
    "#PYY",
    "Filler one",
    "#PQQ",
    "Fixture FWA Alpha",
    143000,
    "100000000000000001",
    "slayer",
  ),
  account(
    "#P22",
    "Filler two",
    "#PRR",
    "Fixture FWA Beta",
    173000,
    "100000000000000002",
    "wizard",
  ),
];
const clans = [
  { tag: "#PQQ", name: "Fixture FWA Alpha", is_fwa: true },
  { tag: "#PRR", name: "Fixture FWA Beta", is_fwa: true },
];
const profiles = accounts.map((a) => ({
  id: a.discord_id,
  display_name: a.discord_name + " fixture",
  username: a.discord_name,
  avatar_url: null,
}));
const candidate = (a) => ({
  player_tag: a.player_tag,
  player_name: a.player_name,
  clan_name: a.current_clan_name,
  weight: a.weight,
  weight_difference: 0,
  town_hall: 14,
  priority: "replace_first",
  active_strikes: 3,
  discord_id: a.discord_id,
  discord_name: a.discord_name,
});
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
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 360, height: 800 },
      hasTouch: true,
      isMobile: true,
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      assert.equal(req.method(), "GET", "check must stay read-only");
      let data = { items: [], entries: [], signups: [], unread_count: 0 };
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
        data = { seasons: [], member_season: { season_id: null, revision: 0 } };
      else if (url.pathname.endsWith("/strikes/accounts"))
        data = { accounts, clans, total: accounts.length };
      else if (url.pathname.endsWith("/strikes/members"))
        data = { options: profiles };
      else if (url.pathname.endsWith("/strikes/replacements")) {
        const weights = url.searchParams.getAll("weight").map(Number);
        const wanted = url.searchParams.getAll("clan");
        data = {
          candidates: [],
          top: [],
          groups: [],
          clans,
          total: 0,
          slots: weights.map((weight) => ({
            weight,
            weight_label: weight / 1000 + "k",
            candidates: accounts
              .filter(
                (a) => !wanted.length || wanted.includes(a.current_clan_tag),
              )
              .map(candidate),
          })),
        };
      } else if (url.pathname.endsWith("/strikes/overview"))
        data = { entries: [], total: 0, summary: {}, clans: [], streak: {} };
      else if (url.pathname.endsWith("/strikes/tracking")) data = { clans: [] };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    });
    await page.goto(origin + "/strikes?activity_view=replacements");
    await page.getByRole("button", { name: "Find slots", exact: true }).tap();
    await page.getByLabel("Weights").waitFor();
    await page.getByLabel("Weights").fill("143, 173");

    // Search first: it replaces the URL under the open panel, and nested
    // panels opened afterwards must still return to it.
    await page.locator(".strike-find-slots-top button.primary").tap();
    await page.locator(".strike-slot-group").first().waitFor();

    // Clans: type, then tap the checkbox.
    await page.getByRole("button", { name: /^Clans:/ }).click();
    await page
      .getByRole("dialog", { name: "Select clans" })
      .getByLabel("Find clan")
      .fill("Alpha");
    await page
      .getByRole("dialog", { name: "Select clans" })
      .getByRole("checkbox", { name: /Fixture FWA Alpha/ })
      .tap();
    await page.waitForTimeout(500);
    await page
      .getByRole("dialog", { name: "Select clans" })
      .getByRole("button", { name: "Close panel" })
      .tap();
    // The Find slots panel stays open underneath, results included.
    await page.waitForFunction(
      () => document.querySelectorAll("dialog[open]").length === 1,
    );
    await page.locator(".strike-slot-group").first().waitFor();
    const clanLabel = await page
      .getByRole("button", { name: /^Clans:/ })
      .getAttribute("aria-label");
    assert.match(
      clanLabel,
      /Fixture FWA Alpha/,
      "clan button shows the tapped clan",
    );

    // Member: type, then tap the option.
    await page.getByRole("button", { name: /^Member:/ }).click();
    await page.getByLabel("Find member").fill("slayer");
    await page
      .getByRole("dialog", { name: "Select member" })
      .getByRole("button", { name: /@slayer/ })
      .first()
      .tap();
    await page.waitForFunction(
      () => document.querySelectorAll("dialog[open]").length === 1,
    );
    const memberLabel = await page
      .getByRole("button", { name: /^Member:/ })
      .getAttribute("aria-label");
    assert.match(
      memberLabel,
      /@slayer/,
      "member button shows the tapped member",
    );
    // Nested Back must return to the Find slots panel with its results.
    await page.getByRole("button", { name: /^Clans:/ }).click();
    await page.getByRole("dialog", { name: "Select clans" }).waitFor();
    await page.goBack();
    await page.waitForFunction(
      () => document.querySelectorAll("dialog[open]").length === 1,
    );
    assert.equal(
      await page.getByRole("dialog", { name: "Find slots" }).isVisible(),
      true,
      "Back from a nested panel keeps Find slots open",
    );
    await page.locator(".strike-slot-group").first().waitFor();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ clanLabel, memberLabel }));
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  server.close();
  process.exitCode = 1;
});
