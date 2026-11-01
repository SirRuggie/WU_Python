const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const port = Number(process.argv[2]);
assert(port > 1024 && port !== 8767);
const origin = `http://127.0.0.1:${port}`;
const output = path.resolve(__dirname, "../../../.local/p76-layout");
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [320, 360, 390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } }),
        errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.route("**/*", (route) =>
        route
          .request()
          .url()
          .startsWith(origin + "/")
          ? route.continue()
          : route.abort(),
      );
      await page.goto(`${origin}/declaration-extras-preview.html?slow=1`);
      await page.locator(".declaration-clan-toggle").first().waitFor();
      assert(
        (await page.locator(".arrival-check").innerText()).includes(
          "Checking clan members",
        ),
      );
      await page.screenshot({
        path: path.join(output, `${width}-rows-first.png`),
        fullPage: true,
      });
      const readinessBefore = await page
        .getByRole("button", { name: /^(Main|Lazy) ·/ })
        .allTextContents();
      const pingBefore = await page
        .getByRole("button", { name: /^Ping \d+ missing$/ })
        .textContent();
      const amber = page
        .locator(".declaration-clan")
        .filter({ hasText: "W. U. Lazy Amber" });
      const flag = amber.locator(".declaration-extras summary");
      await flag.waitFor();
      assert.deepEqual(
        await page
          .getByRole("button", { name: /^(Main|Lazy) ·/ })
          .allTextContents(),
        readinessBefore,
      );
      assert.equal(
        await page
          .getByRole("button", { name: /^Ping \d+ missing$/ })
          .textContent(),
        pingBefore,
      );
      await flag.click();
      assert(
        (await amber.locator(".declaration-extras").innerText()).includes(
          "Assigned to W. U. Lazy Blaze",
        ),
      );
      assert(
        (await amber.locator(".declaration-extras").innerText()).includes(
          "Family member alt",
        ),
      );
      await page.screenshot({
        path: path.join(output, `${width}-expanded.png`),
        fullPage: true,
      });
      const measure = await page.evaluate(() => ({
        width: innerWidth,
        scroll: document.documentElement.scrollWidth,
        targets: [
          ...document.querySelectorAll(
            ".declaration-extras summary,.declaration-extras-filter",
          ),
        ]
          .filter((e) => e.getClientRects().length)
          .map((e) => e.getBoundingClientRect().height),
        color: getComputedStyle(
          document.querySelector(".declaration-extras summary"),
        ).color,
      }));
      assert(measure.scroll <= width + 1, JSON.stringify(measure));
      assert(
        measure.targets.every((n) => n >= 44),
        JSON.stringify(measure),
      );
      assert.equal(measure.color, "rgb(217, 189, 121)");
      await page.getByRole("button", { name: /^Main ·/ }).click();
      assert.equal(await page.locator(".declaration-extras").count(), 0);
      assert.equal(await page.evaluate(() => window.extraReads()), 1);
      await page.getByRole("button", { name: /^Lazy ·/ }).click();
      await page
        .getByRole("checkbox", { name: "Clans with not-on-roster players" })
        .check();
      assert.equal(await page.locator(".declaration-clan-toggle").count(), 1);
      assert.equal(await page.locator(".declaration-extra-only").count(), 1);
      await page.screenshot({
        path: path.join(output, `${width}-filtered.png`),
        fullPage: true,
      });
      await page.goto(`${origin}/declaration-extras-preview.html?failure=1`);
      await page
        .locator(".declaration-clan")
        .filter({ hasText: "W. U. Lazy Amber" })
        .getByText(/Couldn't check/)
        .waitFor();
      const failed = await page
        .locator(".declaration-clan")
        .filter({ hasText: "W. U. Lazy Amber" })
        .innerText();
      assert(!failed.includes("0 not on roster"));
      assert(failed.includes("Last checked"));
      await page.screenshot({
        path: path.join(output, `${width}-failure.png`),
        fullPage: true,
      });
      await page.goto(`${origin}/declaration-extras-preview.html?empty=1`);
      await page
        .getByText(/0 not on roster · Checked/)
        .first()
        .waitFor();
      await page
        .getByRole("checkbox", { name: "Clans with not-on-roster players" })
        .check();
      await page
        .getByRole("button", { name: "Clear filter", exact: true })
        .click();
      assert.equal(await page.locator(".declaration-clan-toggle").count(), 3);
      await page.screenshot({
        path: path.join(output, `${width}-empty.png`),
        fullPage: true,
      });
      await page.goto(`${origin}/declaration-extras-preview.html?omit=1`);
      const missingRow = page.locator(".declaration-clan").filter({hasText: "W. U. Lazy Amber"});
      await missingRow.getByText(/Couldn't check/).waitFor();
      assert(!(await missingRow.innerText()).includes("Checking clan members"));
      assert((await page.locator(".arrival-check").innerText()).includes("couldn't be checked"));
      await page.screenshot({path: path.join(output, `${width}-missing-row.png`), fullPage: true});
      assert.deepEqual(errors, []);
      results.push(measure);
      await page.close();
    }
    fs.writeFileSync(
      path.join(output, "measurements.json"),
      JSON.stringify(results, null, 2),
    );
    console.log(
      JSON.stringify({
        passed: results.length,
        states: ["rows-first", "expanded", "filtered", "failed", "empty"],
        output,
      }),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
