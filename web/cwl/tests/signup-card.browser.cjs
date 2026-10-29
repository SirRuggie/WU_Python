/* Isolated tour fixture only; read-only mock account responses, no signup writes. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const results = [];
  const out = process.env.WU_CARD_EVIDENCE;
  if (out) fs.mkdirSync(out, { recursive: true });
  try {
    await fetch(base + "/qa/member?member=1");
    await fetch(base + "/qa/reset-signups");
    for (const width of [360, 1440]) {
      for (const [scenario, count, closed] of [
        ["open44", 44, false],
        ["open1", 1, false],
        ["closed", 44, true],
        ["all", 0, false],
      ]) {
        await fetch(base + "/qa/scenario?season=" + (closed ? 2 : 1));
        const page = await browser.newPage({
          viewport: { width, height: width === 360 ? 800 : 1000 },
        });
        const errors = [],
          writes = [];
        page.on("pageerror", (e) => errors.push(String(e)));
        await page.addInitScript(() =>
          localStorage.setItem(
            "wu-member-tour-v1",
            JSON.stringify({ skips: 0, dismissed: true }),
          ),
        );
        await page.route("**/*", (route) =>
          new URL(route.request().url()).origin === base
            ? route.continue()
            : route.abort(),
        );
        await page.route("**/api/cwl/linked-accounts?*", async (route) => {
          const response = await route.fetch();
          const data = await response.json();
          const signed = data.accounts.filter((a) =>
            ["#P222222Y", "#Q222222Y"].includes(a.tag),
          );
          data.accounts = [
            ...signed,
            ...Array.from({ length: count }, (_, i) => ({
              tag:
                "#G" +
                i
                  .toString(8)
                  .padStart(7, "0")
                  .replace(/[0-7]/g, (d) => "0289PYLQ"[Number(d)]),
              name: "Unsigned fixture " + i,
              town_hall: 18,
              current_clan_name: null,
            })),
          ];
          data.total = data.accounts.length;
          data.updating = false;
          await route.fulfill({ response, json: data });
        });
        await page.goto(base + "/");
        await page
          .getByRole("button", { name: "Open local test session" })
          .click();
        await page.locator(".member-signup-success").waitFor();
        page.on("request", (r) => {
          if (!["GET", "HEAD"].includes(r.method()))
            writes.push(r.method() + " " + r.url());
        });
        for (const path of ["/", "/assignments"]) {
          if (path !== "/") await page.goto(base + path);
          await page.locator(".member-signup-success").waitFor();
          const red = page.locator(".member-signup-remaining");
          assert.equal(await red.count(), !closed && count > 0 ? 1 : 0);
          const summary = page.locator(".member-signup-summary");
          await summary.scrollIntoViewIfNeeded();
          assert(
            !(await page.evaluate(
              () => document.documentElement.scrollWidth > innerWidth,
            )),
          );
          let measured = null;
          if (!closed && count) {
            assert(!(await red.innerText()).includes("Unsigned fixture"));
            assert.match(
              await red.innerText(),
              new RegExp(
                `${count} account${count === 1 ? "" : "s"} not signed up yet`,
              ),
            );
            assert.match(await red.innerText(), /Signups close/);
            const greenBox = await page
                .locator(".member-signup-success")
                .boundingBox(),
              redBox = await red.boundingBox();
            const button = red.getByRole("button");
            const buttonBox = await button.boundingBox();
            assert(buttonBox.height >= 44);
            assert(
              redBox.y - (greenBox.y + greenBox.height) >= 8 &&
                redBox.y - (greenBox.y + greenBox.height) <= 12,
            );
            const contrast = await red.evaluate((card) => {
              const rgb = (value) =>
                value
                  .match(/[\d.]+/g)
                  .slice(0, 3)
                  .map(Number);
              const luminance = (values) =>
                values
                  .map((v) => {
                    v /= 255;
                    return v <= 0.04045
                      ? v / 12.92
                      : ((v + 0.055) / 1.055) ** 2.4;
                  })
                  .reduce((n, v, i) => n + v * [0.2126, 0.7152, 0.0722][i], 0);
              return [...card.querySelectorAll("h2,p,button")].map((el) => {
                let bg = el;
                while (
                  bg &&
                  getComputedStyle(bg).backgroundColor === "rgba(0, 0, 0, 0)"
                )
                  bg = bg.parentElement;
                const style = getComputedStyle(el),
                  foreground = style.webkitTextFillColor || style.color;
                const background = getComputedStyle(bg).backgroundColor;
                const [a, b] = [
                  luminance(rgb(foreground)),
                  luminance(rgb(background)),
                ].sort((a, b) => b - a);
                return {
                  foreground,
                  background,
                  ratio: (a + 0.05) / (b + 0.05),
                };
              });
            });
            assert(
              contrast.every((c) => c.ratio >= 4.5),
              JSON.stringify(contrast),
            );
            measured = {
              contrast,
              gap: redBox.y - (greenBox.y + greenBox.height),
              buttonHeight: buttonBox.height,
            };
          }
          if (out && path === "/")
            await summary.screenshot({
              path: `${out}/${scenario}-${width}.jpg`,
              type: "jpeg",
              quality: 80,
            });
          results.push({ width, scenario, path, ...measured });
        }
        if (!closed && count) {
          const loaded = page.waitForResponse((r) =>
            r.url().includes("/api/cwl/linked-accounts?"),
          );
          await page.locator(".member-signup-remaining button").click();
          await loaded;
          await page.waitForTimeout(300);
          await page
            .locator('.pool-choice-grid [data-tour-target="signup-pool"]')
            .click();
          try {
            await page
              .locator(".account-select")
              .first()
              .waitFor({ timeout: 5000 });
          } catch (error) {
            console.error(await page.locator("main").innerText());
            throw error;
          }
          assert.equal(
            await page.locator(".account-select input:checked").count(),
            0,
          );
        }
        assert.deepEqual(errors, []);
        assert.deepEqual(writes, []);
        await page.close();
      }
    }
    const state = await (await fetch(base + "/qa/state")).json();
    assert.deepEqual(state.current, state.baseline);
    console.log(
      JSON.stringify({ results, counts: state.current, writes: 0 }, null, 2),
    );
  } finally {
    await fetch(base + "/qa/scenario?season=1");
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
