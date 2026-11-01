const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999);
const origin = `http://127.0.0.1:${port}`;
const output = process.env.WU_TIMEZONE_OUTPUT || "/tmp/wu-timezone-layout";
const profiles = process.env.WU_PROFILE_EXPECTED === "1";
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const [width, height] of [
      [360, 800],
      [1440, 1000],
    ]) {
      const page = await browser.newPage({ viewport: { width, height } });
      const writes = [],
        errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("request", (r) => {
        if (
          r.url().startsWith(origin + "/api/") &&
          !["GET", "HEAD"].includes(r.method()) &&
          !r.url().endsWith("/dev/login")
        )
          writes.push(r.url());
      });
      await page.route("**/*", (route) => {
        const url = new URL(route.request().url());
        if (url.pathname.startsWith("/emojis/"))
          return route.fulfill({
            contentType: "image/svg+xml",
            body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="gold"/></svg>',
          });
        return url.origin === origin ? route.continue() : route.abort();
      });
      await page.addInitScript(
        (columns) =>
          localStorage.setItem(
            "wu-compare-clans:1:main",
            JSON.stringify(columns),
          ),
        width === 1440 ? ["#P2Y", "#Q2Y", "#G2Y"] : ["#P2Y"],
      );
      await page.goto(origin + "/cwl/roster?season=1");
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.locator(".roster-player-card").first().waitFor();
      await page
        .getByRole("button", { name: "Compare clans", exact: true })
        .click();
      await page.locator(".compare-account").first().waitFor();
      await page
        .locator(".compare-toolbar")
        .getByRole("button", { name: /^Sort:/ })
        .click();
      await page
        .getByRole("menuitem", { name: "Time zone", exact: true })
        .click();
      await page.locator(".compare-time-zone").first().waitFor();
      const response = await page.request.get(
        origin + "/api/cwl/seasons/1/roster?background=1",
      );
      assert(response.ok());
      const roster = await response.json();
      const column = page.getByRole("region", {
        name: "Warriors Unite! comparison",
        exact: true,
      });
      const tags = await column
        .locator(".compare-account .player-card-meta-core")
        .allTextContents();
      const owners = tags.map(
        (text) =>
          roster.accounts.find((a) => a.tag === text.split("·")[1].trim())
            .user_id,
      );
      const groups = owners.filter((owner, i) => owner !== owners[i - 1]);
      const ids = Object.keys(roster.owner_nicknames).sort();
      assert.deepEqual(
        groups,
        profiles
          ? [ids[0], ids[2], ids[1], ids[3], ids[5], ids[4]]
          : [ids[0], ids[1], ids[2], ids[5], ids[3], ids[4]],
      );
      if (profiles) {
        assert.equal(roster.owner_timezones[ids[2]].label, "GMT-8");
        assert.equal(roster.owner_timezones[ids[3]].label, "GMT+1");
      }
      const layout = await column.evaluate((el) => ({
        width: innerWidth,
        scroll: document.documentElement.scrollWidth,
        labels: [...el.querySelectorAll(".compare-time-zone")].map((e) => ({
          text: e.textContent,
          height: e.getBoundingClientRect().height,
          right: e.getBoundingClientRect().right,
          cardRight: e.closest("article").getBoundingClientRect().right,
        })),
        rows: [...el.querySelectorAll(".compare-player-meta-line")].map(
          (e) => e.getBoundingClientRect().height,
        ),
      }));
      assert(layout.scroll <= width);
      assert(layout.rows.every((h) => h <= 20));
      const knownOwners = new Set(
        profiles
          ? [ids[0], ids[1], ids[2], ids[3], ids[5]]
          : [ids[0], ids[1], ids[2], ids[5]],
      );
      const expectedLabels = roster.accounts.filter(
        (a) => a.assigned_clan_tag === "#P2Y" && knownOwners.has(a.user_id),
      ).length;
      fs.writeFileSync(
        `${output}/${width}-debug.json`,
        JSON.stringify({ layout, expectedLabels }, null, 2),
      );
      assert.equal(layout.labels.length, expectedLabels);
      assert(
        layout.labels.every((l) => l.height <= 20 && l.right <= l.cardRight),
      );
      assert.deepEqual(writes, []);
      assert.deepEqual(errors, []);
      await page.evaluate(() =>
        window.scrollTo(
          0,
          document.querySelector(".compare-workspace").getBoundingClientRect()
            .top +
            scrollY -
            70,
        ),
      );
      await page.screenshot({ path: `${output}/${width}-time-zone.png` });
      results.push({ ...layout, groups, writes, errors });
      await page.close();
    }
    fs.writeFileSync(
      `${output}/measurements.json`,
      JSON.stringify(results, null, 2),
    );
    console.log(JSON.stringify(results));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
