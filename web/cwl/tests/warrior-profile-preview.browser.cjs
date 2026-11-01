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
        "Australia zones",
        "United States zones",
        "All zones",
        "Preview",
        "Shorten a name",
        "Partial upstream data",
        "Quick Set-up partially applied",
        "Town Hall change partially applied",
        "Role status unavailable",
      ]) {
        await page
          .getByLabel("Example", { exact: true })
          .selectOption({ label: name });
        const region = page.getByRole("region", { name, exact: true });
        await region.waitFor();
        if(name.includes('partially applied')||name==='Role status unavailable'){
          const text=await region.innerText();
          assert(text.includes('Confirmed role changes'));
          assert(text.includes('Return to Warrior Setup'));
          assert(!text.includes('Retry'));
        }
        if (
          ["Australia zones", "United States zones", "All zones"].includes(name)
        ) {
          await region.locator(".discord-mock-select").evaluate(node => {node.open = true;});
          const labels = await region
            .locator(".discord-preview-option")
            .allTextContents();
          if (name === "Australia zones") {
            assert.equal(labels.length, 3);
            assert(labels[0].includes("AEST/AEDT"));
            assert(labels[1].includes("GMT+9:30"));
          }
          if (name === "United States zones") {
            assert.equal(labels.length, 6);
            assert(labels[0].includes("EST/EDT"));
          }
          if (name === "All zones") assert.equal(labels.length, 25);
        }

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
