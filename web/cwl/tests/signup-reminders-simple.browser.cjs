// Optional local browser regression. Execute only with explicit browser authorization.
const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const origin = process.argv[2] || "http://127.0.0.1:33917";
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))
    throw Error("Isolated loopback fixture only");
  const output = process.argv[3] || ".local/260-layout";
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const proof = [];
  try {
    for (const width of [320, 360, 1440])
      for (const mode of [
        "",
        "different",
        "errors",
        "paused",
        "off",
        "pending",
        "offline",
      ]) {
        const height = width === 1440 ? 1000 : 800;
        const page = await browser.newPage({ viewport: { width, height } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(String(error)));
        await page.route("**/*", (route) =>
          new URL(route.request().url()).origin === origin
            ? route.continue()
            : route.abort(),
        );
        await page.goto(
          `${origin}/tests/fixtures/signup-reminders-preview.html?${mode}`,
        );
        const rows = page.locator(".reminder-message-row");
        await rows.nth(5).waitFor();
        if ((await rows.count()) !== 6) throw Error("Missing message row");
        if (
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          )
        )
          throw Error("Horizontal overflow");
        const tabs = await page
          .locator('[aria-label="Reminder sections"] button')
          .evaluateAll((nodes) =>
            nodes.map((node) => ({
              label: node.textContent,
              clipped: node.scrollWidth > node.clientWidth,
            })),
          );
        if (tabs.some((tab) => tab.clipped)) throw Error("Clipped tab label");
        const row6 = await rows.nth(5).boundingBox();
        const toolbar = await page
          .locator(".reminder-list-toolbar > *")
          .evaluateAll((nodes) =>
            nodes.map((node) => node.getBoundingClientRect().top),
          );
        if (Math.max(...toolbar) - Math.min(...toolbar) > 3)
          throw Error("Toolbar wraps");
        if (width === 360 && !mode && row6.y + row6.height > 800)
          throw Error(`Sixth row bottom ${row6.y + row6.height}`);
        if (mode === "errors") {
          await page
            .getByText("2 messages have an error", { exact: true })
            .waitFor();
          if ((await page.locator(".reminder-row-error").count()) !== 2)
            throw Error("Wrong per-pool error marks");
        }
        if (mode === "off") {
          if (
            await page
              .getByRole("button", { name: "Pause reminders", exact: true })
              .count()
          )
            throw Error("Off shows Pause");
          if (
            (await rows.getByText("Not scheduled", { exact: true }).count()) !==
            6
          )
            throw Error("Off implies a send");
        }
        if (mode === "different") {
          await page
            .getByText("Lazy: Different destination", { exact: true })
            .waitFor();
          await page.getByText("Lazy: Off", { exact: true }).waitFor();
        }
        if (mode === "pending")
          await page.getByText("Loading changes…", { exact: true }).waitFor();
        if (mode === "offline")
          await page.getByText("Reminders offline", { exact: true }).waitFor();
        if (width === 1440) {
          const list = await rows.first().boundingBox(),
            editor = await page.locator(".reminder-editor").boundingBox();
          if (editor.x <= list.x + list.width)
            throw Error("Desktop editor is not beside list");
        }
        await page.screenshot({
          path: path.join(output, `${width}-${mode || "base"}.png`),
          fullPage: true,
        });
        if (!mode) {
          await rows.first().click();
          await page
            .getByLabel("Title", { exact: true })
            .fill("Kept fixture edit");
          if (width < 1100) {
            await page
              .getByRole("button", { name: "Back to messages", exact: true })
              .click();
            await rows.first().click();
            if (
              (await page.getByLabel("Title", { exact: true }).inputValue()) !==
              "Kept fixture edit"
            )
              throw Error("Back dropped draft");
            await page.goBack();
            if (await page.locator(".reminder-editor").count())
              throw Error("Browser Back did not close editor");
          }
        }
        const calls = await page.evaluate(() => window.reminderFixture.calls);
        if (calls.some((call) => call.method !== "GET"))
          throw Error("Unexpected fixture write");
        proof.push({
          width,
          height,
          mode: mode || "base",
          row6Y: row6.y,
          row6Bottom: row6.y + row6.height,
          tabs,
          toolbar,
          calls,
          errors,
        });
        if (errors.length) throw Error(errors.join("\n"));
        await page.close();
      }
    fs.writeFileSync(
      path.join(output, "proof.json"),
      JSON.stringify(proof, null, 2),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
