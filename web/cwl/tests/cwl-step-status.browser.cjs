/* Computed accessible names on the real component, isolated fixture only. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    const page = await browser.newPage({
      viewport: { width: 360, height: 800 },
    });
    await page.addInitScript(() =>
      localStorage.setItem(
        "wu-member-tour-v1",
        JSON.stringify({ skips: 3, dismissed: true }),
      ),
    );
    let state = "changed";
    const writes = [];
    page.on("request", (r) => {
      if (
        !["GET", "HEAD"].includes(r.method()) &&
        !r.url().endsWith("/dev/login")
      )
        writes.push(r.method() + " " + new URL(r.url()).pathname);
    });
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== base) return route.abort();
      if (
        url.pathname.endsWith("/publication") &&
        route.request().method() === "GET"
      ) {
        const response = await route.fetch(),
          body = await response.json();
        body.draft_changed = state === "changed";
        body.published = ["changed", "current"].includes(state)
          ? {
              version: 3,
              revision: body.draft_revision,
              published_by: "100000000000000001",
              assigned_count: body.preview.assigned_count,
              unassigned_count: body.preview.unassigned_count,
              published_at: "2026-10-28T16:00:00Z",
              joining_instructions: "",
            }
          : null;
        if (["draft", "empty"].includes(state)) body.last_publication = null;
        if (state === "empty") {
          body.preview.accounts = [];
          body.preview.assigned_count = 0;
          body.preview.unassigned_count = 0;
        }
        return route.fulfill({ response, json: body });
      }
      return route.continue();
    });
    await page.goto(base + "/cwl/roster?season=1");
    await page
      .getByRole("button", { name: "Open local test session", exact: true })
      .click();
    for (const [kind, status] of [
      ["changed", "Unpublished changes"],
      ["current", "Published and current"],
      ["draft", "Unpublished changes"],
      ["empty", ""],
    ]) {
      state = kind;
      await page.reload();
      await page.waitForLoadState("networkidle");
      const name = "Finalize roster" + (status ? " · " + status : "");
      const button = page
        .locator('.cwl-step-strip[aria-label="CWL workflow"]')
        .getByRole("button", { name, exact: true });
      await button.waitFor();
      assert.equal(await button.count(), 1);
      results.push({
        kind,
        computedName: name,
        accessibilitySnapshot: await button.ariaSnapshot(),
      });
    }
    assert.deepEqual(writes, []);
    console.log(
      JSON.stringify({ computedAccessibleNames: results, writes }, null, 2),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
