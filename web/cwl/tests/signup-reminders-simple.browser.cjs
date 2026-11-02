const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const origin = process.argv[2] || "http://127.0.0.1:33917";
  const output = process.argv[3] || ".local/p134-layout";
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const proof = [];
  try {
    for (const width of [360, 1440])
      for (const mode of [
        "",
        "different",
        "paused",
        "off",
        "pending",
        "offline",
      ]) {
        const page = await browser.newPage({
          viewport: { width, height: 900 },
        });
        const errors = [];
        page.on("pageerror", (error) => errors.push(String(error)));
        await page.route("**/*", (route) =>
          new URL(route.request().url()).origin === origin
            ? route.continue()
            : route.abort(),
        );
        await page.goto(`${origin}/signup-reminders-preview.html?${mode}`);
        await page
          .getByRole("heading", { name: "Messages for December 2026 CWL" })
          .waitFor();
        const rows = page.locator(".signup-reminder-row");
        if ((await rows.count()) !== 6) throw Error("Missing reminder row");
        if (mode === "different") {
          await page
            .getByText("Destination: Different destination", { exact: true })
            .waitFor();
          await page
            .getByText("Notify: Different notify", { exact: true })
            .waitFor();
          if (!(await page.getByText("Disabled", { exact: true }).count()))
            throw Error("Disabled hidden");
        }
        if (mode === "pending")
          await page
            .getByText("Waiting for the bot to load changes", { exact: true })
            .waitFor();
        else if (mode === "offline")
          await page.getByText("Bot offline", { exact: true }).waitFor();
        else if (
          await page
            .getByText("Waiting for the bot to load changes", { exact: true })
            .count()
        )
          throw Error("False warning");
        if (
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          )
        )
          throw Error("Overflow");
        await page.screenshot({
          path: path.join(output, `${width}-${mode || "matching"}.png`),
          fullPage: true,
        });
        proof.push({
          width,
          mode: mode || "matching",
          rows: await rows.count(),
          errors,
        });
        if (errors.length) throw Error(errors.join("\n"));
        if (!mode) {
          const edits = await rows.locator("button").count();
          for (let index = 0; index < edits; index++) {
            const label = await rows.locator("button").nth(index).textContent();
            await rows.locator("button").nth(index).click();
            const selected = await page
              .locator("label")
              .filter({ hasText: "Message to edit" })
              .locator("select")
              .inputValue();
            const pool = index % 2 ? "lazy" : "main";
            if (!label.includes(pool === "main" ? "Main" : "Lazy"))
              throw Error("Wrong Edit label");
            const audience = page
              .getByRole("group", { name: "Message audience" })
              .getByRole("button", {
                name: pool === "main" ? "Main" : "Lazy",
                exact: true,
              });
            if ((await audience.getAttribute("aria-pressed")) !== "true")
              throw Error("Wrong pool");
            proof.push({ width, edit: index, message: selected, pool });
            await page
              .getByRole("group", { name: "Reminder sections" })
              .getByRole("button", { name: "Overview", exact: true })
              .click();
          }
          await page
            .getByRole("button", { name: "Pause reminders", exact: true })
            .click();
          await page.getByRole("dialog").waitFor();
          await page
            .getByRole("dialog")
            .getByRole("button", { name: "Pause reminders", exact: true })
            .click();
          await page
            .getByRole("button", { name: "Resume reminders", exact: true })
            .waitFor();
          const writes = await page.evaluate(() =>
            window.reminderFixture.calls.filter(
              (call) => call.method !== "GET",
            ),
          );
          if (writes.length !== 1 || !writes[0].path.endsWith("/pause"))
            throw Error("Unexpected writes");
        }
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
