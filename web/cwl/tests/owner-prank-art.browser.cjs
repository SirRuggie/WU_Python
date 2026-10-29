/* Render every owner prank WebP with the real card styles at phone and desktop widths. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const styles = [
  "../src/memberTour/tour.css",
  "../src/ownerPrank/ownerPrank.css",
]
  .map((file) => fs.readFileSync(path.join(__dirname, file), "utf8"))
  .join("\n");
const assetDir = path.join(__dirname, "../../../cwl_web/owner_prank_assets");
const assets = fs
  .readdirSync(assetDir)
  .filter((file) => file.endsWith(".webp"));

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  try {
    for (const width of [360, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width === 360 ? 800 : 1000 },
      });
      for (const file of assets) {
        const finalCard = file === "final-aq.webp";
        const wide = file === "102809.webp" || file === "102845.webp";
        const art = `data:image/webp;base64,${fs.readFileSync(path.join(assetDir, file), "base64")}`;
        await page.setContent(`
          <style>${styles}</style>
          <dialog class="owner-prank-dialog" open>
            <article class="tour-card owner-prank-card has-art${finalCard ? " farewell" : ""}${wide ? " wide-character" : ""}">
              <img class="owner-prank-character" src="${art}" alt="">
              <div class="owner-prank-copy">
                <h2>The owner prank has a long heading</h2>
                <p>Next time you see a big scary button, maybe ask Ruggie to supervise you. Just a thought.</p>
                <footer><button>Continue</button></footer>
              </div>
            </article>
          </dialog>`);
        await page
          .locator(".owner-prank-character")
          .evaluate((image) => image.decode());
        const bounds = await page.evaluate(() => {
          const rect = (selector) => {
            const { left, right, top, bottom, width, height } = document
              .querySelector(selector)
              .getBoundingClientRect();
            return { left, right, top, bottom, width, height };
          };
          const image = document.querySelector(".owner-prank-character");
          const art = rect(".owner-prank-character");
          const scale = Math.min(
            art.width / image.naturalWidth,
            art.height / image.naturalHeight,
          );
          return {
            card: rect(".owner-prank-card"),
            art,
            paintedWidth: scale * image.naturalWidth,
            paintedHeight: scale * image.naturalHeight,
            heading: rect("h2"),
            paragraph: rect("p"),
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
          };
        });
        const minimumHeight = finalCard
          ? width === 360
            ? 220
            : 280
          : width === 360
            ? 140
            : 160;
        assert(
          bounds.paintedHeight >= minimumHeight - 1,
          `${file} at ${width}px painted ${bounds.paintedHeight}px tall`,
        );
        assert(bounds.art.width <= bounds.art.height, file);
        assert(bounds.art.top < bounds.card.top, `${file} must pop above card`);
        assert(
          bounds.card.right <= bounds.clientWidth,
          `${file} card overflow`,
        );
        assert(
          bounds.scrollWidth <= bounds.clientWidth,
          `${file} caused horizontal scroll`,
        );
        for (const text of [bounds.heading, bounds.paragraph]) {
          assert(
            text.left >= bounds.art.right || text.top >= bounds.art.bottom,
            `${file} overlaps card text at ${width}px`,
          );
        }
      }
      await page.close();
    }
    console.log(
      `Owner prank art layout passed for ${assets.length} WebPs at 360px and 1440px`,
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
