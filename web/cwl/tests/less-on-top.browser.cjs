const { chromium } = require("playwright");
const fs = require("node:fs"),
  path = require("node:path"),
  assert = require("node:assert/strict");
const staff = process.env.WU_LESS_STAFF_URL,
  member = process.env.WU_LESS_MEMBER_URL,
  output = process.env.WU_LAYOUT_OUTPUT;
for (const base of [staff, member]) {
  const url = new URL(base);
  assert.equal(url.hostname, "127.0.0.1");
  assert(![8766, 8767].includes(Number(url.port)));
}
fs.mkdirSync(output, { recursive: true });
const now = Math.floor(Date.now() / 1000),
  last = {
    token: "a".repeat(32),
    actor_id: "local-reviewer",
    actor_name: "Local reviewer",
    state: "done",
    created_at: now - 1800,
    count: 3,
    chunks: 1,
    posted: [{ chunk: 0, message_id: "234567890123456789" }],
    attempting: null,
    channel: { id: "123456789012345678", name: "sample" },
  };
const ping = {
  revision: 1,
  channel: last.channel,
  can_send: true,
  channels: [{ ...last.channel, type: 0, can_send: true }],
  active: null,
  test_running: false,
  history: [last],
  cooldown_until: 0,
  test_channel: { id: "345678901234567890", name: "sample-test", revision: 1 },
};
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const cases = [],
    writes = [],
    errors = [];
  async function ready(page) {
    await page.waitForLoadState("networkidle");
    for (const text of [
      "Updating live clan details… Saved assignments are ready.",
      "Checking linked accounts…",
    ])
      await page
        .getByText(text, { exact: true })
        .waitFor({ state: "hidden", timeout: 15000 });
  }
  async function pageFor(base, width) {
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
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("request", (request) => {
      if (
        !["GET", "HEAD"].includes(request.method()) &&
        !request.url().endsWith("/dev/login")
      )
        writes.push({
          method: request.method(),
          path: new URL(request.url()).pathname,
        });
    });
    const mode = {
      publicationFailure: false,
      visibilityFailure: false,
      seasonsReads: 0,
      pingFailure: false,
      uncertain: false,
    };
    await page.route("**/*", async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (url.origin !== base) return route.abort();
      if (request.method() !== "GET") return route.continue();
      const fail = () =>
        route.fulfill({
          status: 503,
          headers: { "X-Read-Retries-Exhausted": "1" },
          json: { error: "Local sample read failure" },
        });
      if (base === staff) {
        if (
          url.pathname === "/api/cwl/seasons" &&
          ++mode.seasonsReads > 1 &&
          mode.visibilityFailure
        )
          return fail();
        if (url.pathname.endsWith("/publication") && mode.publicationFailure)
          return fail();
        if (/\/declaration-pings\/(main|lazy)$/.test(url.pathname))
          return mode.pingFailure
            ? fail()
            : route.fulfill({
                json: mode.uncertain
                  ? {
                      ...ping,
                      history: [],
                      active: {
                        ...last,
                        state: "uncertain",
                        error: "Local uncertain delivery",
                      },
                    }
                  : ping,
              });
        if (url.pathname.endsWith("/arrival-check")) {
          const response = await route.fetch(),
            value = await response.json();
          const known = value.accounts.find(
            (account) => account.assigned_clan_tag,
          )?.assigned_clan_tag;
          return route.fulfill({
            response,
            json: {
              ...value,
              updating: false,
              accounts: value.accounts.map((account) => ({
                ...account,
                current_clan_tag:
                  account.assigned_clan_tag === known ? known : null,
                current_clan_name:
                  account.assigned_clan_tag === known
                    ? account.assigned_clan_name
                    : null,
                current_clan_checked_at:
                  account.assigned_clan_tag === known
                    ? new Date().toISOString()
                    : null,
                current_clan_status:
                  account.assigned_clan_tag === known
                    ? "current"
                    : "unavailable",
              })),
            },
          });
        }
        if (url.pathname.endsWith("/declaration-extras"))
          return route.fulfill({
            json: { source: "published", basis: 3, clans: [] },
          });
        if (url.pathname.endsWith("/manage-bridge")) {
          const pool = {
            channel_id: last.channel.id,
            title: "Local roster",
            body: "Synthetic only",
            media_url: null,
            buttons: [],
            role_ids: [],
            enabled: true,
            delivery: null,
            roster_url: null,
          };
          return route.fulfill({
            json: {
              cycle: "2026-11",
              generation: "fixture",
              worker_ready: true,
              published_version: 3,
              pools: { main: pool, lazy: pool },
            },
          });
        }
      }
      return route.continue();
    });
    return { context, page, mode };
  }
  async function setup(page, base, query) {
    const response = await page.request.get(
      base + "/qa/less-on-top/setup?" + query,
    );
    assert(response.ok(), "Fixture setup failed: " + response.status());
    return response.json();
  }
  async function noOverflow(page) {
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      "Horizontal overflow: " + page.url(),
    );
  }
  async function shot(page, name, width) {
    if ([360, 1440].includes(width))
      await page.screenshot({
        path: path.join(output, name + "-" + width + ".png"),
      });
  }
  try {
    for (const width of [320, 360, 390, 1440])
      for (const count of [26, 65, 125]) {
        const { context, page, mode } = await pageFor(staff, width);
        await setup(page, staff, "count=" + count);
        await page.request.post(staff + "/api/cwl/dev/login");
        const before = (
          await (await page.request.get(staff + "/qa/state")).json()
        ).current;
        await page.goto(staff + "/cwl/roster?season=1");
        await page.locator(".roster-player-card").first().waitFor();
        await ready(page);
        const metrics = await page.evaluate(() => {
          const rect = (selector) => {
            const r = document.querySelector(selector).getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height };
          };
          return {
            clan: rect(".roster-clan-chip"),
            player: rect(".roster-player-card"),
            toolbar: [
              ...document.querySelectorAll(".roster-filters-toolbar>button"),
            ].map((button) => ({
              name: button.getAttribute("aria-label") || button.innerText,
              ...rect(".roster-filters-toolbar"),
            })),
          };
        });
        if (width === 360) assert(metrics.clan.y < 340);
        if (width === 1440) assert(metrics.player.y < 500);
        const refresh = page
          .locator(".roster-filters-toolbar")
          .getByRole("button", { name: "Refresh roster", exact: true });
        assert(await refresh.isVisible());
        let reads = 0;
        const observed = (request) => {
          if (new URL(request.url()).pathname.endsWith("/roster")) reads++;
        };
        page.on("request", observed);
        await refresh.focus();
        await page.keyboard.press("Enter");
        await ready(page);
        assert(reads > 0, "Refresh must actually reread the roster");
        page.off("request", observed);
        for (const button of await page
          .locator(".roster-filters-toolbar>button")
          .all()) {
          const box = await button.boundingBox();
          assert(box.width >= 44 && box.height >= 44);
        }
        const filters = page.getByRole("button", {
          name: "Filters",
          exact: true,
        });
        await filters.focus();
        await page.keyboard.press("Enter");
        await page.getByRole("dialog").waitFor();
        await page.keyboard.press("Escape");
        await page.getByRole("dialog").waitFor({ state: "hidden" });
        await page.getByRole("button", { name: /^Sort:/ }).click();
        await page.getByRole("dialog", { name: "Sort accounts" }).waitFor();
        await page.keyboard.press("Escape");
        await page
          .getByRole("group", { name: "CWL account pool" })
          .getByRole("button", { name: "Main CWL", exact: true })
          .click();
        await page
          .getByRole("group", { name: "CWL account pool" })
          .getByRole("button", { name: "All accounts", exact: true })
          .click();
        await noOverflow(page);
        const status = page.locator(".roster-header-status[role=status]");
        assert(await status.isVisible());
        if (count === 125) await shot(page, "build", width);
        cases.push({
          kind: "build",
          width,
          count,
          firstClan: metrics.clan.y,
          firstPlayer: metrics.player.y,
          refreshRead: true,
        });
        if (count === 125) {
          mode.publicationFailure = true;
          await page.reload();
          await page
            .getByText("Publication status unavailable", { exact: true })
            .waitFor();
          assert.equal(
            await page.locator(".roster-header-summary").getAttribute("open"),
            null,
          );
          const retry = page.getByRole("button", {
            name: "Retry status",
            exact: true,
          });
          assert(await retry.isVisible());
          assert.equal(
            await retry.evaluate((button) => !!button.closest("details")),
            false,
          );
          await shot(page, "publication-failure", width);
          mode.publicationFailure = false;
          await retry.click();
          await page.waitForFunction(() =>
            document
              .querySelector(".roster-header-status")
              ?.textContent.includes("Published v3"),
          );
          cases.push({ kind: "visible-publication-retry", width });
          mode.visibilityFailure = true;
          mode.seasonsReads = 0;
          await page.reload();
          await page.getByText(/Couldn't check signup visibility/).waitFor();
          assert(await page.locator(".roster-header-signups").isVisible());
          await shot(page, "visibility-failure", width);
          mode.visibilityFailure = false;
          cases.push({ kind: "visible-signup-visibility-failure", width });
          await page.goto(staff + "/cwl/readiness?season=1");
          await page.locator(".declaration-clan-toggle").first().waitFor();
          await ready(page);
          const once = await page
            .locator(
              ".declaration-summary,.declaration-pools,.declaration-clan-toggle",
            )
            .allTextContents();
          assert.equal(
            once.join(" ").match(/Locations unavailable/g)?.length,
            1,
          );
          const season = page.locator(".declaration-page-head select");
          const fit = await season.evaluate((select) => {
            const css = getComputedStyle(select),
              canvas = document.createElement("canvas"),
              ctx = canvas.getContext("2d");
            ctx.font = css.font;
            return {
              text: ctx.measureText(select.selectedOptions[0].text).width,
              room:
                select.clientWidth -
                parseFloat(css.paddingLeft) -
                parseFloat(css.paddingRight) -
                20,
            };
          });
          assert(fit.text <= fit.room, JSON.stringify({ width, fit }));
          const disclosure = page.locator(".declaration-ping-panel");
          assert.equal(await disclosure.getAttribute("open"), null);
          await disclosure
            .locator(":scope>summary")
            .getByText(/Last pinged/)
            .waitFor();
          await disclosure.locator(":scope>summary").focus();
          await page.keyboard.press("Enter");
          await page
            .locator(".declaration-ping-controls")
            .waitFor({ state: "visible" });
          await disclosure.locator(":scope>summary").focus();
          await page.keyboard.press("Enter");
          const pools = page.locator(".declaration-pools");
          await pools.getByRole("button", { name: /^Lazy(?: ·|$)/ }).focus();
          await page.keyboard.press("Enter");
          assert.equal(
            await pools
              .getByRole("button", { name: /^Lazy(?: ·|$)/ })
              .getAttribute("aria-pressed"),
            "true",
          );
          await pools.getByRole("button", { name: /^Main(?: ·|$)/ }).click();
          await ready(page);
          await noOverflow(page);
          await shot(page, "declaration", width);
          cases.push({
            kind: "declaration",
            width,
            monthFits: true,
            unavailableOnce: true,
          });
          mode.pingFailure = true;
          await page.reload();
          const jump = page.getByRole("button", {
            name: "View error ›",
            exact: true,
          });
          await jump.waitFor();
          const alert = page.locator(".declaration-ping-attention");
          assert((await alert.boundingBox()).y < 800);
          assert.equal(await disclosure.getAttribute("open"), "");
          assert(
            !(await disclosure.locator(":scope>summary").innerText()).includes(
              "Checking last ping",
            ),
          );
          await shot(page, "ping-settings-failure-top", width);
          await jump.click();
          assert.equal(
            await page.evaluate(() =>
              document.activeElement?.getAttribute("role"),
            ),
            "alert",
          );
          cases.push({ kind: "ping-error-jump", width });
          mode.pingFailure = false;
          mode.uncertain = true;
          await page.reload();
          await page
            .getByText("Declaration pings: Local uncertain delivery", {
              exact: true,
            })
            .waitFor();
          assert.equal(await disclosure.getAttribute("open"), "");
          mode.uncertain = false;
          cases.push({ kind: "uncertain-ping-visible", width });
          for (const step of ["review", "announce"]) {
            await page.goto(staff + "/cwl/publish?season=1&step=" + step);
            await page
              .getByRole("heading", {
                name: step === "review" ? "Finalize roster" : "Announcements",
                exact: true,
              })
              .waitFor();
            await ready(page);
            const overlap = await page
              .locator(".publication-workspace>.page-head")
              .evaluate((head) => {
                const a = head.querySelector("h1").getBoundingClientRect(),
                  b = head
                    .querySelector(".roster-menu-trigger")
                    .getBoundingClientRect();
                return {
                  sameRow: a.y < b.bottom && b.y < a.bottom,
                  eyebrows: head.querySelectorAll(".eyebrow").length,
                };
              });
            assert(overlap.sameRow);
            assert.equal(overlap.eyebrows, 0);
            await noOverflow(page);
            await shot(page, step, width);
            cases.push({ kind: step, width });
          }
        }
        assert.deepEqual(
          (await (await page.request.get(staff + "/qa/state")).json()).current,
          before,
        );
        await context.close();
      }
    for (const width of [320, 360, 390, 1440]) {
      const { context, page } = await pageFor(member, width);
      await setup(page, member, "mode=open");
      await page.request.post(member + "/api/cwl/dev/login");
      const before = (
        await (await page.request.get(member + "/qa/state")).json()
      ).current;
      await page.goto(member + "/my-signups?season=6");
      await page.locator(".saved-signup-card").first().waitFor();
      await ready(page);
      assert(!(await page.locator("main").innerText()).includes("No campaign"));
      assert(
        (await page.locator(".member-season-line").innerText()).includes(
          "Signups open",
        ),
      );
      assert.equal(await page.locator(".member-signup-success ul").count(), 0);
      const names = await page
        .locator(".saved-signup-card .signed-up-name>span:last-child")
        .allTextContents();
      assert.equal(names.length, 2);
      const guidance = page.getByText(/^Changing pools or withdrawing/);
      assert.equal(await guidance.count(), 1);
      for (const name of names)
        assert((await guidance.innerText()).includes(name));
      let confirm;
      page.once("dialog", async (dialog) => {
        confirm = dialog.message();
        await dialog.dismiss();
      });
      await page
        .locator(".saved-signup-card")
        .first()
        .getByRole("button", { name: "Withdraw signup", exact: true })
        .click();
      assert(
        confirm.includes(
          "Clan assignments will be cleared for: " + names[0] + ".",
        ),
      );
      assert(
        !confirm.includes(
          "Clan assignments will be cleared for: " + names[1] + ".",
        ),
      );
      await noOverflow(page);
      await shot(page, "my-signups", width);
      cases.push({ kind: "my-signups-open-withdraw-cancel", width });
      await setup(page, member, "mode=closed");
      await page.goto(member + "/signup?season=2");
      await page
        .getByRole("heading", { name: "Signups closed", exact: true })
        .waitFor();
      await ready(page);
      assert.equal(
        (await page.locator("main").innerText()).match(/Signups closed/g)
          ?.length,
        1,
      );
      await noOverflow(page);
      await shot(page, "signup-closed", width);
      cases.push({ kind: "signup-closed", width });
      await page.goto(member + "/my-signups?season=2");
      await page.locator(".saved-signup-card").first().waitFor();
      await ready(page);
      assert.equal(
        (await page.locator("main").innerText()).match(/Signups closed/g)
          ?.length,
        1,
      );
      assert.equal(
        await page.getByText(/^Changing pools or withdrawing/).count(),
        0,
      );
      await shot(page, "my-signups-closed", width);
      assert.deepEqual(
        (await (await page.request.get(member + "/qa/state")).json()).current,
        before,
      );
      cases.push({ kind: "my-signups-closed", width });
      await context.close();
    }
    assert.equal(cases.filter((item) => item.kind === "build").length, 12);
    assert.deepEqual(
      [...new Set(cases.map((item) => item.width))].sort((a, b) => a - b),
      [320, 360, 390, 1440],
    );
    assert.equal(cases.length, 52);
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(output, "results.json"),
      JSON.stringify(
        {
          cases,
          writes,
          errors,
          fixtureOnly: true,
          developmentBannerExcluded: true,
          syntheticGETResponses: [
            "ping settings/history",
            "arrival locations",
            "extras",
            "bridge",
          ],
        },
        null,
        2,
      ),
    );
    console.log(
      JSON.stringify({
        layoutCases: cases.length,
        widths: [320, 360, 390, 1440],
        accountCounts: [26, 65, 125],
        writes,
        errors,
      }),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
