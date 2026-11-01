const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const port = Number(process.argv[2]);
assert(port > 1024 && port !== 8767);
const origin = `http://127.0.0.1:${port}`,
  out = path.resolve(__dirname, "../../../.local/p79-layout");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const measures = [];
  try {
    for (const width of [320, 360, 390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.route("**/*", (r) =>
        r
          .request()
          .url()
          .startsWith(origin + "/")
          ? r.continue()
          : r.abort(),
      );
      await page.goto(origin + "/base-bank-preview.html");
      await page
        .getByRole("link", {
          name: "Copy TH18 merged defenses base",
          exact: true,
        })
        .waitFor();
      assert.equal(await page.evaluate(() => window.detailReads()), 0);
      assert.deepEqual(
        await page
          .locator(".base-bank-card")
          .evaluateAll((rows) => rows.map((r) => r.getAttribute("aria-label"))),
        ["TH18 Merged defenses", "TH18 Non-merged defenses"],
      );
      const m = await page.evaluate(() => ({
        width: innerWidth,
        scroll: document.documentElement.scrollWidth,
        cards: [...document.querySelectorAll(".base-bank-card")].map((r) => {
          const b = r.getBoundingClientRect();
          return { x: b.x, y: b.y, width: b.width };
        }),
        targets: [
          ...document.querySelectorAll(
            ".base-bank button,.base-bank a,.base-bank summary",
          ),
        ].map((e) => e.getBoundingClientRect().height),
        images: [...document.images].map((i) => ({
          fit: getComputedStyle(i).objectFit,
          lazy: i.loading,
          alt: i.alt,
        })),
      }));
      assert(m.scroll <= width + 1, JSON.stringify(m));
      assert(
        m.targets.every((h) => h >= 44),
        JSON.stringify(m),
      );
      assert(
        m.images.every(
          (i) =>
            i.fit === "contain" &&
            i.lazy === "lazy" &&
            i.alt.includes("war base"),
        ),
      );
      if (width < 650) assert(m.cards[1].y > m.cards[0].y);
      else assert.equal(m.cards[1].y, m.cards[0].y);
      await page.screenshot({
        path: path.join(out, `${width}-cards.png`),
        fullPage: true,
      });
      await page.locator(".base-bank-card details summary").first().click();
      await page.getByText("Sample only.", { exact: false }).first().waitFor();
      assert.equal(await page.evaluate(() => window.detailReads()), 1);
      assert.equal(await page.locator(".base-bank-details img").count(), 0);
      await page
        .getByRole("button", { name: "Town Hall 17", exact: true })
        .click();
      assert.equal(await page.locator(".base-bank-card").count(), 1);
      await page.goto(origin + "/base-bank-preview.html?missing=1");
      await page.getByText("Base link coming soon").waitFor();
      assert.equal(
        await page.getByRole("link", { name: /Copy TH18 non-merged/ }).count(),
        0,
      );
      await page.screenshot({
        path: path.join(out, `${width}-missing.png`),
        fullPage: true,
      });
      await page.goto(origin + "/base-bank-preview.html?linked17=1");
      await page
        .getByRole("link", {
          name: "Copy TH17 merged defenses base",
          exact: true,
        })
        .waitFor();
      await page.goto(origin + "/base-bank-preview.html?empty=1");
      await page
        .getByText("No bases are available yet.", { exact: false })
        .waitFor();
      await page.goto(origin + "/base-bank-preview.html?failure=1");
      await page.getByRole("alert").waitFor();
      assert.equal(await page.locator(".base-bank-card").count(), 0);
      await page.goto(origin + "/base-bank-preview.html?denied=1");
      await page
        .getByText("Sign in again to view Base bank.", { exact: false })
        .waitFor();
      assert.equal(await page.locator(".base-bank-card").count(), 0);
      assert.deepEqual(errors, []);
      measures.push(m);
      await page.close();
    }
    fs.writeFileSync(
      path.join(out, "measurements.json"),
      JSON.stringify(measures, null, 2),
    );
    console.log(
      JSON.stringify({ passed: 4, states: 7, readonly: true, output: out }),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
