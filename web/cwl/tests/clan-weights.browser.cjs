const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs"),
  path = require("node:path");
const origin = `http://127.0.0.1:${Number(process.argv[2])}`;
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    for (const width of [320, 360, 390, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width < 700 ? 800 : 1000 },
      });
      await page.route("**/*", (r) =>
        new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
      );
      await page.goto(origin + "/clan-weights");
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.locator(".weight-trial-clan-list button").first().click();
      await page.waitForFunction(
        () => document.querySelectorAll(".weight-trial-row").length === 52,
      );
      const geometry = await page.evaluate(() => {
        const root = document.querySelector(".weight-trial");
        const visible = (n) => {
          const r = n.getBoundingClientRect(),
            s = getComputedStyle(n);
          return (
            r.width > 1 &&
            r.height > 1 &&
            s.display !== "none" &&
            s.visibility === "visible" &&
            !n.closest(".weight-trial-sr-only")
          );
        };
        const nodes = [...root.querySelectorAll("*")].filter(visible);
        return {
          width: document.documentElement.scrollWidth,
          height: document.documentElement.scrollHeight,
          rows: [...root.querySelectorAll(".weight-trial-row")].map(
            (n) => n.getBoundingClientRect().height,
          ),
          small: nodes
            .filter(
              (n) =>
                [...n.childNodes].some(
                  (c) => c.nodeType === 3 && c.textContent.trim(),
                ) && parseFloat(getComputedStyle(n).fontSize) < 12,
            )
            .map((n) => n.className),
          short: nodes
            .filter(
              (n) =>
                n.matches("button,input,select,summary,a") &&
                n.getBoundingClientRect().height < 44,
            )
            .map((n) => n.outerHTML),
        };
      });
      assert.equal(geometry.width, width, "horizontal overflow");
      assert.equal(geometry.rows.length, 52);
      assert.deepEqual(geometry.small, []);
      assert.deepEqual(geometry.short, []);
      assert(geometry.rows[0] <= (width < 800 ? 110 : 80), "normal row height");
      assert(
        geometry.rows[1] <= (width < 800 ? 110 : 80),
        "ordinary row height",
      );
      const full = page.locator(".weight-trial-phone-full").first();
      if (width < 800) {
        assert(await full.isVisible(), "phone Full must be visible");
        assert.equal(
          await full.evaluate((n) => getComputedStyle(n).visibility),
          "visible",
          "phone Full computed visibility",
        );
        assert(
          await full.evaluate(
            (n) => parseFloat(getComputedStyle(n).opacity) > 0,
          ),
        );
      }
      const warSelector = page.locator(".weight-trial-war-picker select");
      assert.equal(await warSelector.inputValue(), "20261102T070000.000Z");
      assert(
        await page
          .locator('[data-player="#V2Y"] .weight-trial-loot input')
          .isEnabled(),
      );
      assert(
        (await page.locator('[data-player="#V2Y"]').textContent()).includes(
          "Left clan",
        ),
      );
      assert.equal(
        await page.locator('[data-player="#U2Y"] select').inputValue(),
        "",
      );
      await warSelector.selectOption("20261031T070000.000Z");
      assert(
        await page
          .locator('[data-player="#Y2Y"] .weight-trial-loot input')
          .isEnabled(),
      );
      assert.equal(await page.locator('[data-player="#U2Y"]').count(), 0);
      await warSelector.selectOption("20261102T070000.000Z");
      const cdp = await page.context().newCDPSession(page);
      for (const pointer of ["fine", "coarse"]) {
        if (pointer === "coarse")
          await cdp.send("Emulation.setTouchEmulationEnabled", {
            enabled: true,
            maxTouchPoints: 1,
          });
        await cdp.send("Emulation.setEmulatedMedia", {
          features: [{ name: "pointer", value: pointer }],
        });
        const state = await page.evaluate(() => ({
          fine: matchMedia("(pointer: fine)").matches,
          display: getComputedStyle(
            document.querySelector(".weight-keyboard-hint"),
          ).display,
        }));
        assert.equal(state.fine, pointer === "fine");
        assert.equal(
          state.display,
          pointer === "fine" ? "block" : "none",
          "rendered keyboard hint",
        );
      }
      await page
        .getByRole("button", { name: "Missing (3)", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Next missing ›", exact: true })
        .click();
      await page.waitForFunction(() =>
        document.activeElement?.matches(".weight-trial-loot input"),
      );
      const input = await page
        .locator(".weight-trial-loot input:focus")
        .elementHandle();
      for (const ch of "32.2k") {
        await page.keyboard.type(ch);
        assert(
          await input.evaluate(
            (n) => n.isConnected && n === document.activeElement,
          ),
        );
      }
      assert.equal(await input.inputValue(), "32.2k");
      assert.equal(
        await input.evaluate(
          (node) =>
            !!node
              .closest(".weight-trial-row")
              .querySelector(".weight-trial-row-error"),
        ),
        false,
        "edited row remains valid",
      );
      if (process.env.WU_LAYOUT_ARTIFACT_DIR) {
        fs.mkdirSync(process.env.WU_LAYOUT_ARTIFACT_DIR, { recursive: true });
        await page.screenshot({
          path: path.join(
            process.env.WU_LAYOUT_ARTIFACT_DIR,
            `clan-weights-${width}.png`,
          ),
          fullPage: true,
        });
      }
      console.log(
        JSON.stringify({
          feature: "clan-weights",
          viewport: width,
          ...geometry,
          computedFullVisibility: true,
          pointerFineAndCoarse: true,
        }),
      );
      await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
