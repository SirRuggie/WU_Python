const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const origin = process.argv[2] || "http://127.0.0.1:34017";
  const output = process.argv[3] || ".local/p140-layout";
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const proof = [];
  try {
    for (const width of [320, 360, 390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 800 } });
      const errors = [];
      page.on("pageerror", (error) => errors.push(String(error)));
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === origin
          ? route.continue()
          : route.abort(),
      );
      await page.goto(origin + "/return-reminders-simple-preview.html");
      await page
        .getByRole("checkbox", { name: "Select Local clan AAA", exact: true })
        .waitFor();
      if (
        await page
          .locator(".return-row-actions")
          .getByRole("button", { name: "Change frequency", exact: true })
          .count()
      )
        throw Error("Row frequency remains");
      if (
        await page
          .getByRole("region", { name: "Clan selection", exact: true })
          .count()
      )
        throw Error("Selection bar premature");
      await page.screenshot({
        path: path.join(output, `${width}-overview.png`),
        fullPage: true,
      });
      await page
        .getByRole("checkbox", { name: "Select Local clan AAA", exact: true })
        .focus();
      await page.keyboard.press("Space");
      const bar = page.getByRole("region", {
        name: "Clan selection",
        exact: true,
      });
      await bar.waitFor();
      if (await page.locator(".return-batch").count())
        throw Error("Action preselected");
      async function action(label) {
        if (width < 768) {
          await bar
            .getByRole("button", { name: "Actions", exact: true })
            .click();
          await page
            .getByRole("menuitem", { name: label, exact: true })
            .focus();
          await page.keyboard.press("Enter");
        } else {
          await bar.getByRole("button", { name: label, exact: true }).focus();
          await page.keyboard.press("Enter");
        }
      }
      await action("Select all");
      await page
        .getByRole("button", { name: "5 selected", exact: true })
        .waitFor();
      if (await page.locator(".return-batch").count())
        throw Error("Select all picked action");
      await page.screenshot({
        path: path.join(output, `${width}-selection.png`),
        fullPage: true,
      });
      await action("Change frequency");
      await page
        .getByRole("heading", {
          name: "Change frequency · 5 clans",
          exact: true,
        })
        .waitFor();
      await page
        .locator(".return-batch")
        .getByRole("button", { name: "Cancel", exact: true })
        .click();
      await page
        .getByRole("button", { name: "5 selected", exact: true })
        .waitFor();
      await action("Change frequency");
      const review = page.locator(".return-review-scope");
      if (
        !(await review.getByText(/Local clan BBB · Paused/).count()) ||
        !(await review.getByText(/Local clan DDD · No saved list/).count())
      )
        throw Error("Skipped names hidden");
      for (const text of [
        "currently every 30 minutes",
        "currently every hour",
        "currently every 2 hours",
      ])
        if (!(await review.textContent()).includes(text))
          throw Error("Current frequencies hidden");
      await page.locator(".return-batch select").selectOption("120");
      await page
        .getByRole("button", { name: "Review action", exact: true })
        .click();
      const dialog = page.getByRole("dialog");
      await dialog
        .getByRole("button", {
          name: "Change frequency for 3 clans",
          exact: true,
        })
        .waitFor();
      if (!(await dialog.textContent()).includes("Local clan BBB"))
        throw Error("Skipped absent from confirmation");
      await page.screenshot({
        path: path.join(output, `${width}-confirm.png`),
        fullPage: true,
      });
      await dialog
        .getByRole("button", {
          name: "Change frequency for 3 clans",
          exact: true,
        })
        .click();
      await page
        .getByText("Local clan CCC: failed (fixture)", { exact: false })
        .waitFor();
      const writes = await page.evaluate(() =>
        window.returnFixture.calls.filter((call) => call.method === "POST"),
      );
      if (
        writes.length !== 1 ||
        writes[0].path !== "/manage/return-bulk/resume/run"
      )
        throw Error("Unexpected send/start or duplicate request");
      if (
        JSON.stringify(writes[0].body.values.clans) !==
        JSON.stringify(["FWA:#AAA", "FWA:#CCC", "FWA:#EEE"])
      )
        throw Error("Wrong applicable clans");
      if (writes[0].body.values.every_minutes !== 120)
        throw Error("Frequency not shared");
      await page.screenshot({
        path: path.join(output, `${width}-results.png`),
        fullPage: true,
      });
      await page.getByRole("button", { name: "Done", exact: true }).click();
      if (
        (await page
          .getByRole("checkbox", { name: /Select Local clan/ })
          .evaluateAll(
            (nodes) => nodes.filter((node) => node.checked).length,
          )) !== 5
      )
        throw Error("Selection lost on Back/refresh");
      if (
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        )
      )
        throw Error("Overflow");
      proof.push({
        width,
        selected: 5,
        applied: 3,
        skipped: ["BBB", "DDD"],
        writes,
        errors,
      });
      // A filter retains selection but hidden clans are explicitly skipped, never written.
      await action("Select none");
      await page
        .getByRole("checkbox", { name: "Select Local clan AAA", exact: true })
        .check();
      await page
        .getByRole("checkbox", { name: "Select Local clan BBB", exact: true })
        .check();
      await page.getByPlaceholder("Find a clan").fill("CCC");
      await page
        .getByRole("checkbox", { name: "Select Local clan CCC", exact: true })
        .check();
      await action("Change frequency");
      await page
        .locator(".return-review-scope")
        .getByText(/Local clan AAA · Hidden by the current filters/)
        .waitFor();
      await page
        .getByRole("button", { name: "Review action", exact: true })
        .click();
      await page
        .getByRole("dialog")
        .getByRole("button", {
          name: "Change frequency for 1 clan",
          exact: true,
        })
        .click();
      await page.getByRole("button", { name: "Done", exact: true }).waitFor();
      const hiddenWrites = await page.evaluate(() =>
        window.returnFixture.calls.filter((call) => call.method === "POST"),
      );
      if (
        JSON.stringify(hiddenWrites[1].body.values.clans) !==
        JSON.stringify(["FWA:#CCC"])
      )
        throw Error("Hidden clan acted on");
      await page.screenshot({
        path: path.join(output, `${width}-hidden-results.png`),
        fullPage: true,
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
