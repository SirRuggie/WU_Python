const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const b = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    for (const width of [320, 360, 390, 1440]) {
      const p = await b.newPage({ viewport: { width, height: 1000 } });
      await p.goto("http://127.0.0.1:44792/pool-roles-preview.html");
      const select = p.getByRole("combobox", { name: /^Main role/ });
      await select.focus();
      await p.waitForFunction(() =>
        window.fixtureMethods.some((line) => line.includes("choices=1")),
      );
      await select.selectOption("333333333333333333");
      await p
        .getByRole("button", { name: "Save Main role", exact: true })
        .click();
      const dialog = p.getByRole("dialog");
      await dialog.waitFor();
      assert(
        await dialog
          .getByText("Adds role to 91 members", { exact: true })
          .isVisible(),
      );
      assert.equal(
        await dialog
          .getByRole("button", { name: "Keep current setting" })
          .evaluate((e) => e === document.activeElement),
        true,
      );
      await p.keyboard.press("Tab");
      assert.equal(
        await dialog
          .getByRole("button", { name: "Save role", exact: true })
          .evaluate((e) => e === document.activeElement),
        true,
      );
      await p.keyboard.press("Tab");
      assert.equal(
        await dialog
          .getByRole("button", { name: "Keep current setting" })
          .evaluate((e) => e === document.activeElement),
        true,
      );
      assert(
        await p.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await p.screenshot({
        path: path.resolve(
          __dirname,
          `../../../.local/p95-layout/confirm-${width}.png`,
        ),
        fullPage: true,
      });
      await p.keyboard.press("Escape");
      assert.equal(
        await p
          .getByRole("button", { name: "Save Main role", exact: true })
          .evaluate((e) => e === document.activeElement),
        true,
      );
      assert(
        (await p.evaluate(() => window.fixtureMethods)).every((m) =>
          m.startsWith("GET "),
        ),
      );
      await p
        .getByRole("button", { name: "Save Main role", exact: true })
        .click();
      await p.getByRole("button", { name: "Save role", exact: true }).click();
      await p.getByText("Role saved. Updates are queued.").waitFor();
      assert.equal(
        (await p.evaluate(() => window.fixtureMethods)).filter((m) =>
          m.startsWith("POST "),
        ).length,
        1,
      );
      await p.close();
    }
    console.log("Four confirm/cancel/focus/one in-memory save cases pass");
  } finally {
    await b.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
