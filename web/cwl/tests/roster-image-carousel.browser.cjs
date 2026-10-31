const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`,
  out = process.env.WU_CAROUSEL_EVIDENCE || "/tmp/wu-carousel-review";
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  try {
    for (const width of [320, 360, 390, 1440]) {
      const context = await browser.newContext({
        viewport: { width, height: width < 500 ? 800 : 1000 },
      });
      await context.route("**/*", (route) =>
        new URL(route.request().url()).origin === base
          ? route.continue()
          : route.abort(),
      );
      const page = await context.newPage(),
        errors = [],
        pngs = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("request", (r) => {
        if (r.url().includes(".png?version=")) pngs.push(r.url());
      });
      await page.goto(base + "/?view=publication&step=announce&season=1");
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page
        .getByText("Clan roster images & testing", { exact: true })
        .click();
      await page.getByText("Single-clan test", { exact: true }).first().click();
      const carousel = page.locator(".roster-image-carousel");
      await carousel.waitFor();
      async function settle() {
        await page.waitForFunction(() => {
          const rail = document.querySelector(".image-carousel-rail"),
            card = rail?.querySelector('[aria-hidden="false"]');
          return (
            rail &&
            card &&
            Math.abs(
              card.getBoundingClientRect().left -
                rail.getBoundingClientRect().left,
            ) < 2 &&
            [...card.querySelectorAll("img")].every(
              (img) => img.complete && img.naturalWidth > 0,
            )
          );
        });
        await carousel.evaluate((e) =>
          window.scrollTo({
            top: window.scrollY + e.getBoundingClientRect().top - 80,
            behavior: "instant",
          }),
        );
      }

      await carousel.scrollIntoViewIfNeeded();
      await page
        .locator('.image-carousel-card[aria-hidden="false"] img')
        .first()
        .waitFor();
      await page.waitForFunction(() =>
        [
          ...document.querySelectorAll(
            '.image-carousel-card[aria-hidden="false"] img',
          ),
        ].every((img) => img.complete && img.naturalWidth > 0),
      );
      const first = await page.locator(".image-carousel-position").innerText();
      const initialTags = new Set(pngs.map((url) => new URL(url).pathname));
      assert(initialTags.size <= 4, "initial image loading is not bounded");
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "page overflow",
      );
      await settle();
      await page.screenshot({ path: `${out}/${width}-first.png` });
      await page
        .getByRole("button", { name: "Next clan", exact: true })
        .click();
      await page.waitForFunction(() =>
        document
          .querySelector(".image-carousel-position")
          ?.textContent.includes("Clan 2 of"),
      );
      const rail = page.locator(".image-carousel-rail");
      await rail.evaluate((e) => {
        e.dispatchEvent(new Event("pointerdown"));
        e.scrollTo({ left: e.clientWidth * 2, behavior: "instant" });
      });
      await page.waitForFunction(() =>
        document
          .querySelector(".image-carousel-position")
          ?.textContent.includes("Clan 3 of"),
      );
      await settle();
      await page.screenshot({ path: `${out}/${width}-after-swipe.png` });
      const data = await (
        await context.request.get(base + "/api/cwl/seasons/1/roster-images")
      ).json();
      const multi = data.clans.find((clan) => clan.pages >= 2);
      assert(multi);
      await page.locator(".image-carousel-position button").click();
      await page
        .locator(".image-carousel-jump button")
        .filter({ hasText: multi.name })
        .click();
      await page.waitForFunction(() =>
        [
          ...document.querySelectorAll(
            '.image-carousel-card[aria-hidden="false"] img',
          ),
        ].every((img) => img.complete && img.naturalWidth > 0),
      );
      assert.equal(
        await page
          .locator('.image-carousel-card[aria-hidden="false"] img')
          .count(),
        multi.pages,
      );
      await settle();
      await page.screenshot({ path: `${out}/${width}-two-images.png` });
      const measures = await carousel
        .locator("button:visible")
        .evaluateAll((elements) =>
          elements.map((e) => ({
            text: e.textContent,
            height: e.getBoundingClientRect().height,
            font: parseFloat(getComputedStyle(e).fontSize),
          })),
        );
      assert(
        measures.every((m) => m.height >= 44 && m.font >= 12),
        JSON.stringify(measures),
      );
      assert.deepEqual(errors, []);
      console.log(
        JSON.stringify({
          width,
          first,
          multi: multi.name,
          pages: multi.pages,
          initialImageUrls: initialTags.size,
          measures,
          errors,
        }),
      );
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
