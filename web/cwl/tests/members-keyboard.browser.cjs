const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const origin =
  "http://127.0.0.1:" +
  fs
    .readFileSync(
      path.resolve(__dirname, "../../../.local/p93-preview-port"),
      "utf8",
    )
    .trim();
const out = path.resolve(__dirname, "../../../.local/p93-keyboard");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const [width, height] of [
      [360, 1000],
      [1440, 1000],
      [640, 460],
    ]) {
      const page = await browser.newPage({ viewport: { width, height } });
      const posts = [];
      page.on("request", (r) => {
        if (r.method() === "POST" && r.url().includes("/manage/"))
          posts.push(r.url());
      });
      await page.route("**/*", (r) =>
        new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
      );
      await page.goto(origin + "/server/members");
      await page
        .getByRole("button", { name: /Open local test session/i })
        .click();
      await page.locator(".members-person").first().waitFor();
      await page
        .getByPlaceholder("Name, nickname, username or Discord ID")
        .focus();
      await page.keyboard.type("Birch");
      await page.waitForFunction(
        () => document.querySelectorAll(".members-person").length === 1,
      );
      let steps = 0;
      while (
        !(await page.evaluate(() =>
          document.activeElement?.matches(".members-person input"),
        )) &&
        steps++ < 35
      )
        await page.keyboard.press("Tab");
      assert(steps < 35, "Row checkbox not reachable by Tab");
      await page.keyboard.press("Space");
      await page
        .getByRole("button", { name: "1 selected", exact: true })
        .waitFor();
      await page.keyboard.press("Tab");
      assert(
        await page.evaluate(() =>
          document.activeElement?.matches(".members-person-open"),
        ),
        "Checkbox and open action must be separate keyboard targets",
      );
      console.log(JSON.stringify(await page.evaluate(() => {
        const e=document.activeElement,r=e.getBoundingClientRect(),bar=document.querySelector('.members-bulk-bar').getBoundingClientRect();
        return {width:innerWidth,row:{top:r.top,bottom:r.bottom},bar:{top:bar.top,bottom:bar.bottom},hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.className};
      })));
      await page.screenshot({path:path.join(out,`focus-before-${width}.png`),fullPage:false});
      assert(
        await page.evaluate(() => {
          const e = document.activeElement,
            r = e.getBoundingClientRect(),
            hit = document.elementFromPoint(
              r.x + r.width / 2,
              r.y + r.height / 2,
            );
          return (
            r.top >= 0 && r.bottom <= innerHeight && !!hit && e.contains(hit)
          );
        }),
        "Sticky controls must not cover focused row",
      );
      await page.keyboard.press("Enter");
      await page
        .getByRole("button", { name: "Back to members", exact: true })
        .waitFor();
      assert(
        await page.evaluate(
          () => document.activeElement?.textContent === "Back to members",
        ),
      );
      assert(new URL(page.url()).searchParams.has("account"));
      await page.keyboard.press("Tab");
      await page.keyboard.press("Escape");
      await page.waitForFunction(
        () => !document.querySelector(".details-frame"),
      );
      assert(
        await page.evaluate(() =>
          document.activeElement?.matches(".members-person-open"),
        ),
        "Back must restore row focus",
      );
      assert.equal(
        await page
          .getByPlaceholder("Name, nickname, username or Discord ID")
          .inputValue(),
        "Birch",
      );
      assert.equal(
        await page.locator(".members-person input:checked").count(),
        1,
      );
      assert.deepEqual(posts, []);
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      if (height < 500)
        assert.equal(
          await page
            .locator(".members-bulk-bar")
            .evaluate((e) => getComputedStyle(e).position),
          "static",
        );
      await page.screenshot({
        path: path.join(out, `${width}-${height}.png`),
        fullPage: true,
      });
      results.push({
        width,
        height,
        tabSteps: steps,
        rowFocusUncovered: true,
        spaceSelect: true,
        enterOpen: true,
        escapeBack: true,
        selectionPreserved: true,
        noWrite: true,
      });
      await page.close();
    }
    fs.writeFileSync(
      path.join(out, "results.json"),
      JSON.stringify(results, null, 2),
    );
    console.log(
      "Three keyboard/short-screen/focus/selection/no-write cases pass",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
