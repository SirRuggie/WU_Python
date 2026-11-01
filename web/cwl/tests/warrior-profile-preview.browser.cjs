const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2]);
assert(port > 1024 && port <= 65535 && port !== 8767);
const origin = `http://127.0.0.1:${port}`;
const output = process.env.WU_WARRIOR_OUTPUT || "/tmp/p62-warrior-layout";
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [360, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width === 360 ? 800 : 1000 },
      });
      const writes = [],
        errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("request", (r) => {
        if (!["GET", "HEAD"].includes(r.method())) writes.push(r.url());
      });
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === origin
          ? route.continue()
          : route.abort(),
      );
      await page.goto(origin + "/tests/fixtures/warrior-profile-preview.html");
      await page.getByLabel("Example", { exact: true }).waitFor();
      for (const name of [
        "Choose an account",
        "No links",
        "Country",
        "Time zone",
        "Preview",
        "Shorten a name",
        "Partial upstream data",
      ]) {
        await page
          .getByLabel("Example", { exact: true })
          .selectOption({ label: name });
        const region = page.getByRole("region", { name, exact: true });
        await region.waitFor();
        if (name === "Preview")
          assert(
            await page
              .getByLabel("Preview button: Set nickname", { exact: true })
              .count(),
          );
        if (name === "Shorten a name")
          assert.equal(
            await page
              .getByLabel("Preview button: Set nickname", { exact: true })
              .count(),
            0,
          );
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        );
        await page.screenshot({
          path: `${output}/${width}-${name.replaceAll(" ", "-")}.png`,
          fullPage: true,
        });
        results.push({ width, case: name, overflow: false });
      }
      assert.deepEqual(writes, []);
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(
    output + "/measurements.json",
    JSON.stringify(results, null, 2),
  );
  console.log(JSON.stringify(results));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
