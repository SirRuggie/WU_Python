const { chromium } = require("../node_modules/playwright");
const fs = require("node:fs"),
  path = require("node:path");
const base = process.argv[2],
  out = process.argv[3];
if (!base || !out) throw Error("usage: URL output-dir");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const proof = [];
  try {
    for (const width of [320, 360, 390, 1440]) {
      const context = await browser.newContext({
        viewport: { width, height: 800 },
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.route("**/*", (r) =>
        r.request().url().startsWith(base) ? r.continue() : r.abort(),
      );
      await page.goto(base + "/return-reminders-simple-preview.html");
      await page
        .getByRole("button", { name: "Change frequency", exact: true })
        .waitFor();
      async function capture(state) {
        const layout = await page.evaluate(() => ({
          firstClanTop:
            document.querySelector(".return-clan-row")?.getBoundingClientRect()
              .top ?? null,
          scroll: document.documentElement.scrollWidth,
          width: innerWidth,
          controls: [
            ...document.querySelectorAll("button,input,select,summary"),
          ]
            .filter(
              (n) =>
                n.getClientRects().length &&
                n.getBoundingClientRect().width > 25,
            )
            .map((n) => ({
              text: n.textContent?.slice(0, 40) || n.getAttribute("type"),
              height: n.getBoundingClientRect().height,
            })),
        }));
        if (layout.scroll > width + 1)
          throw Error("overflow " + JSON.stringify({ width, state, layout }));
        await page.screenshot({
          path: path.join(out, `${width}-${state}.png`),
          fullPage: true,
        });
        proof.push({ width, state, ...layout });
      }
      await capture("overview");
      const firstTop = await page
        .locator(".return-clan-row")
        .first()
        .evaluate((node) => node.getBoundingClientRect().top);
      if (width === 360 && firstTop >= 300)
        throw Error("First clan too low: " + firstTop);
      if (await page.locator(".return-select-all").count())
        throw Error("Select all shown before a tick");
      if (await page.locator(".members-filter-panel select").isVisible())
        throw Error("Status not disclosed");
      await page.getByText("Filters", { exact: true }).focus();
      await page.keyboard.press("Enter");
      await page.locator(".members-filter-panel select").selectOption("paused");
      if ((await page.locator(".return-clan-row").count()) !== 1)
        throw Error("Status filter failed");
      await capture("filters");
      await page.locator(".members-filter-panel select").focus();
      await page.keyboard.press("Escape");
      if (
        await page
          .locator(".members-more-filters")
          .evaluate((node) => node.open)
      )
        throw Error("Filters Escape failed");
      await page.locator(".members-more-filters summary").click();
      await page.locator(".members-filter-panel select").selectOption("all");
      await page.locator(".members-filter-panel select").focus();
      await page.keyboard.press("Escape");
      await page
        .getByRole("button", { name: "Actions for Return reminders" })
        .click();
      await page
        .getByRole("menuitem", { name: "About this page", exact: true })
        .click();
      await page.getByRole("dialog").waitFor();
      await capture("about");
      await page.keyboard.press("Escape");
      if (await page.getByRole("dialog").count())
        throw Error("About Escape failed");
      await page
        .getByRole("button", { name: "Actions for Return reminders" })
        .click();
      page.once("dialog", (dialog) => dialog.dismiss());
      await page
        .getByRole("menuitem", { name: "Return channels", exact: true })
        .click();
      await page.getByLabel("Select Local clan AAA", { exact: true }).check();
      await page.locator(".return-select-all").waitFor();
      await capture("selection");
      await page
        .getByRole("button", { name: "Clear selection", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Change frequency", exact: true })
        .click();
      await page.locator(".return-batch select").selectOption("120");
      await page.getByRole("button", { name: "Review action" }).click();
      await page.getByRole("dialog").waitFor();
      await capture("frequency-confirm");
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Change frequency", exact: true })
        .focus();
      await page.keyboard.press("Enter");
      await page.getByText("Local fixture saved. No message sent.").waitFor();
      const writes = await page.evaluate(() =>
        window.returnFixture.calls.filter((c) => c.method === "POST"),
      );
      if (
        writes.length !== 1 ||
        writes[0].path != "/manage/return-bulk/resume/run"
      )
        throw Error(JSON.stringify(writes));
      await page.getByRole("button", { name: "Done", exact: true }).click();
      await page.evaluate(() => window.returnFixture.failRefresh(500));
      await page
        .getByRole("button", { name: "Actions for Return reminders" })
        .click();
      await page
        .getByRole("menuitem", { name: "Refresh", exact: true })
        .click();
      await page.getByRole("alert").waitFor();
      await capture("refresh-error");
      if (
        await page
          .getByRole("button", { name: "Change frequency", exact: true })
          .isDisabled()
      )
        throw Error("stale controls disabled");
      await page.getByRole("button", { name: "Retry", exact: true }).click();
      await page.evaluate(() => window.returnFixture.failRefresh(403));
      await page
        .getByRole("button", { name: "Actions for Return reminders" })
        .click();
      await page
        .getByRole("menuitem", { name: "Refresh", exact: true })
        .click();
      await page.getByRole("alert").waitFor();
      if (await page.locator(".return-clan-row").count())
        throw Error("auth rows retained");
      await capture("denied");
      if (errors.length) throw Error(errors.join("\n"));
      await context.close();
    }
    fs.writeFileSync(
      path.join(out, "proof.json"),
      JSON.stringify(proof, null, 2),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
