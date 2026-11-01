const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999);
const origin = `http://127.0.0.1:${port}`;
const output =
  process.env.WU_MEMBER_ZONE_OUTPUT || "/tmp/wu-member-timezones-ui";
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const evidence = [];
  try {
    for (const [width, height] of [
      [360, 800],
      [1440, 1000],
    ]) {
      const page = await browser.newPage({ viewport: { width, height } });
      const errors = [],
        writes = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("request", (r) => {
        if (
          r.url().startsWith(origin + "/api/") &&
          !["GET", "HEAD"].includes(r.method())
        )
          writes.push({ method: r.method(), path: new URL(r.url()).pathname });
      });
      page.on("dialog", (d) => d.accept());
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === origin
          ? route.continue()
          : route.abort(),
      );
      await page.request.post(origin + "/qa/member-timezones", {
        data: { denied: false, conflict: false },
      });
      await page.goto(origin + "/server/member-timezones");
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page
        .getByRole("heading", { name: "Member time zones", exact: true })
        .waitFor();
      await page
        .getByRole("button", { name: "Edit Ada Champion", exact: true })
        .waitFor();
      const scope = page.locator(".member-timezones");
      assert.equal(await page.locator(".mt-member-row").count(), 25);
      await page.getByText("560 of 560 members", { exact: false }).waitFor();
      const compact = await page
        .locator(".mt-member-row")
        .first()
        .evaluate((e) => ({
          height: e.getBoundingClientRect().height,
          rows: document.querySelectorAll(".mt-member-row").length,
          actionsAbove:
            document.querySelector(".mt-top-actions").getBoundingClientRect()
              .top < e.getBoundingClientRect().top,
        }));
      assert(
        compact.height >= 70 && compact.height <= 90 && compact.actionsAbove,
        JSON.stringify(compact),
      );
      for (const state of ["Saved", "From nickname", "Unknown", "Missing"])
        assert((await scope.textContent()).includes(state));
      assert(!writes.some((r) => r.path.endsWith("/preview")));
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: `${output}/${width}-overview.png`,
        fullPage: false,
      });
      await page
        .getByRole("button", { name: "Edit Ada Champion", exact: true })
        .click();
      await page
        .getByLabel("Which one do you want to name it?", { exact: true })
        .selectOption("#PQQ");
      assert.equal(
        await page.getByLabel("In-game name", { exact: true }).inputValue(),
        "Second Main",
      );
      await page.request.post(origin + "/qa/member-timezones", {
        data: { conflict: true },
      });
      await page
        .getByRole("button", { name: "Save profile", exact: true })
        .click();
      await page
        .getByRole("alert")
        .filter({ hasText: "Member profile changed" })
        .waitFor();
      assert.equal(
        await page.getByLabel("In-game name", { exact: true }).inputValue(),
        "Second Main",
      );
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: `${output}/${width}-conflict.png`,
        fullPage: false,
      });
      await page.request.post(origin + "/qa/member-timezones", {
        data: { conflict: false },
      });
      await page
        .getByRole("button", { name: "Save profile", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Edit Ada Champion", exact: true })
        .waitFor();
      assert.equal(
        await page.evaluate(() =>
          document.activeElement?.getAttribute("data-member-id"),
        ),
        "123456789012345670",
      );
      await page.getByText("Standardize nicknames", { exact: true }).click();
      await page
        .getByRole("button", {
          name: "Preview all nickname changes",
          exact: true,
        })
        .click();
      await page
        .getByRole("heading", { name: "Review all 560 members" })
        .waitFor();
      const checks = scope.locator("input[type=checkbox]");
      assert(
        !(await checks.nth(2).isChecked()),
        "Unknown suffix is never default selected",
      );
      await checks.nth(1).uncheck();
      const confirmed = await checks.evaluateAll(
        (inputs) => inputs.filter((e) => e.checked).length,
      );
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: `${output}/${width}-preview.png`,
        fullPage: false,
      });
      await scope
        .locator(".mt-list li")
        .filter({ hasText: "Cedar" })
        .scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${output}/${width}-needs-review.png` });
      await page
        .getByRole("button", {
          name: `Confirm ${confirmed} nickname changes`,
          exact: true,
        })
        .click();
      await page.getByText(/1 need manual checking/).waitFor();
      await page.getByRole("button", { name: "Stop run", exact: true }).click();
      await page
        .getByRole("heading", { name: /Standardize progress · Stopped/ })
        .waitFor();
      assert(
        (await scope.textContent()).includes(
          "Stopped before this member started.",
        ),
      );
      await page.evaluate(() => window.scrollTo(0, 0));
      await page
        .getByRole("heading", { name: /Standardize progress · Stopped/ })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: `${output}/${width}-results.png`,
        fullPage: false,
      });
      await page.getByText("Standardize nicknames", { exact: true }).click();
      await page
        .getByLabel("Search members", { exact: true })
        .fill("Server owner");
      await page.getByRole("button", { name: /Edit Server owner/ }).click();
      await page
        .locator(".mt-editor")
        .getByText("The server owner cannot be changed by this tool.", {
          exact: true,
        })
        .waitFor();
      await page.screenshot({ path: `${output}/${width}-owner-guard.png` });
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      const geometry = await scope.evaluate((node) => ({
        overflow: document.documentElement.scrollWidth > innerWidth,
        small: [...node.querySelectorAll("button,select,summary")]
          .filter(
            (e) =>
              e.getBoundingClientRect().height &&
              e.getBoundingClientRect().height < 44,
          )
          .map((e) => e.textContent),
      }));
      assert(!geometry.overflow, `Overflow at${width}`);
      assert.equal(geometry.small.length, 0, JSON.stringify(geometry));
      assert.equal(errors.length, 0, errors.join("\n"));
      assert(
        writes.every((r) =>
          /\/dev\/login$|\/manage\/member-timezones\/(save|preview|confirm|runs\/fixture-run\/stop)$/.test(
            r.path,
          ),
        ),
        JSON.stringify(writes),
      );
      evidence.push({ width, height, compact, geometry, errors, writes });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(
    output + "/measurements.json",
    JSON.stringify(evidence, null, 2),
  );
  console.log(JSON.stringify(evidence));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
