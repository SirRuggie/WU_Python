const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const port = Number(process.argv[2]);
assert(port > 1024 && port !== 8767);
const origin = `http://127.0.0.1:${port}`;
const output = path.resolve(__dirname, "../../../.local/p74-layout");
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [320, 360, 390, 1440])
      for (const count of [26, 65, 125]) {
        const page = await browser.newPage({
          viewport: { width, height: 800 },
        });
        const errors = [];
        page.on("pageerror", (e) => errors.push(e.message));
        await page.route("**/*", (route) =>
          route
            .request()
            .url()
            .startsWith(origin + "/")
            ? route.continue()
            : route.abort(),
        );
        await page.goto(
          `${origin}/declaration-ping-preview.html?count=${count}`,
        );
        await page
          .getByRole("button", { name: `Ping ${count} missing`, exact: true })
          .waitFor();
        await page.screenshot({
          path: path.join(output, `${count}-${width}-controls.png`),
          fullPage: true,
        });
        const before = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          width: innerWidth,
          targets: [
            ...document.querySelectorAll(".declaration-ping-panel button"),
          ]
            .filter((e) => e.getClientRects().length)
            .map((e) => ({
              text: e.textContent,
              height: e.getBoundingClientRect().height,
            })),
        }));
        assert(before.scroll <= before.width + 1, JSON.stringify(before));
        assert(
          before.targets.every((t) => t.height >= 44),
          JSON.stringify(before),
        );
        await page
          .getByRole("button", { name: `Ping ${count} missing`, exact: true })
          .click();
        const dialog = page.getByRole("dialog");
        await dialog.waitFor();
        assert((await dialog.innerText()).includes(`Ping ${count} players`));
        assert((await dialog.innerText()).includes("No linked Discord"));
        await page.screenshot({
          path: path.join(output, `${count}-${width}-confirm.png`),
          fullPage: true,
        });
        await dialog
          .getByText("Review the rendered messages", { exact: true })
          .click();
        await dialog.getByLabel(/Chunk 1 of/).waitFor();
        await page.screenshot({
          path: path.join(output, `${count}-${width}-rendered.png`),
          fullPage: true,
        });
        const modal = await dialog.evaluate((el) => ({
          scroll: el.scrollWidth,
          width: el.clientWidth,
          left: el.getBoundingClientRect().left,
          right: el.getBoundingClientRect().right,
          viewport: innerWidth,
        }));
        assert(modal.scroll <= modal.width + 1, JSON.stringify(modal));
        assert(
          modal.left >= 0 && modal.right <= modal.viewport + 1,
          JSON.stringify(modal),
        );
        await dialog
          .getByRole("button", { name: "Cancel", exact: true })
          .click();
        await page.getByText("No-ping test", { exact: true }).click();
        await page
          .getByRole("button", { name: "Send test", exact: true })
          .click();
        await page
          .getByRole("dialog")
          .getByText(/Nobody will be pinged/)
          .waitFor();
        await page
          .getByRole("dialog")
          .getByRole("button", { name: "Cancel", exact: true })
          .click();
        await page.goto(
          `${origin}/declaration-ping-preview.html?count=${count}&post=1`,
        );
        await page.getByLabel(/Chunk 1 of/).waitFor();
        await page.screenshot({
          path: path.join(output, `${count}-${width}-post.png`),
          fullPage: true,
        });
        assert.deepEqual(errors, []);
        results.push({ width, count, ...before, modal });
        await page.close();
      }
    const page = await browser.newPage({
      viewport: { width: 360, height: 800 },
    });
    await page.goto(`${origin}/declaration-ping-preview.html?readonly=1`);
    await page.getByText(/Read-only access/).waitFor();
    assert.equal(
      await page.locator(".declaration-ping-panel button").count(),
      0,
    );
    await page.screenshot({
      path: path.join(output, "readonly-360.png"),
      fullPage: true,
    });
    fs.writeFileSync(
      path.join(output, "measurements.json"),
      JSON.stringify(results, null, 2),
    );
    console.log(
      JSON.stringify({ passed: results.length, output, readonly: true }),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
