/* Actual App shell, loopback static files and read-only detached API fixtures. */
const { createServer } = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const dist = path.resolve(__dirname, "../dist");
const output = process.env.WU_STORAGE_LAYOUT_OUTPUT;
assert(output, "Explicit owned evidence directory required");
fs.mkdirSync(output, { recursive: true });
const server = createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  let file = path.resolve(dist, "." + url.pathname);
  if (
    !file.startsWith(dist + path.sep) ||
    !fs.existsSync(file) ||
    fs.statSync(file).isDirectory()
  )
    file = path.join(dist, "index.html");
  res.setHeader(
    "Content-Type",
    file.endsWith(".js")
      ? "text/javascript"
      : file.endsWith(".css")
        ? "text/css"
        : "text/html",
  );
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const evidence = [];
  try {
    for (const width of [360, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [],
        requests = [];
      let degraded = false;
      page.on("pageerror", (error) => errors.push(error.message));
      await page.route("**/*", async (route) => {
        const request = route.request(),
          url = new URL(request.url());
        if (url.origin !== origin) return route.abort();
        if (!url.pathname.startsWith("/api/")) return route.continue();
        assert.equal(
          request.method(),
          "GET",
          "Status layout must remain read-only",
        );
        requests.push(url.pathname);
        if (url.pathname.endsWith("/auth/me") && degraded)
          return route.fulfill({
            status: 503,
            headers: {
              "X-Dashboard-Storage-Degraded": "1",
              "X-Read-Retries-Exhausted": "1",
            },
            contentType: "application/json",
            body: JSON.stringify({
              error:
                "Dashboard storage is recovering; saves are temporarily unavailable.",
            }),
          });
        let data = {
          items: [],
          accounts: [],
          members: [],
          entries: [],
          signups: [],
          unread_count: 0,
        };
        if (url.pathname.endsWith("/auth/me"))
          data = {
            authenticated: true,
            user: { id: "123456789012345678", username: "Fixture staff" },
            is_owner: false,
            can_edit: true,
            dashboard_permissions: ["strikes"],
            csrf_token: "fixture",
          };
        else if (url.pathname.endsWith("/config")) data = { dev_fixture: true };
        else if (url.pathname.endsWith("/seasons"))
          data = {
            seasons: [],
            member_season: { season_id: null, revision: 0 },
          };
        else if (url.pathname.endsWith("/strikes/accounts"))
          data = { accounts: [], clans: [], total: 0 };
        else if (url.pathname.endsWith("/strikes/overview"))
          data = { entries: [], total: 0, summary: {}, clans: [], streak: {} };
        else if (url.pathname.endsWith("/strikes/tracking"))
          data = { clans: [] };
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(data),
        });
      });
      await page.goto(origin + "/strikes");
      await page.locator("#dashboard-main").waitFor();
      degraded = true;
      await page.evaluate(() => window.dispatchEvent(new Event("focus")));
      const notice = page.getByRole("alert").filter({
        hasText:
          "Dashboard storage is recovering. Saves are temporarily unavailable.",
      });
      await notice.waitFor();
      assert.equal(await notice.count(), 1);
      assert(await page.locator("#dashboard-main").isVisible());
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await page.screenshot({
        path: path.join(output, `${width}-degraded.png`),
        fullPage: false,
      });
      degraded = false;
      await page.evaluate(() => window.dispatchEvent(new Event("focus")));
      await notice.waitFor({ state: "detached" });
      await page.screenshot({
        path: path.join(output, `${width}-recovered.png`),
        fullPage: false,
      });
      assert.deepEqual(errors, []);
      evidence.push({
        width,
        noOverflow: true,
        warningVisibleThenCleared: true,
        sessionRetained: true,
        requests,
        pageErrors: errors,
      });
      await page.close();
    }
    fs.writeFileSync(
      path.join(output, "evidence.json"),
      JSON.stringify(evidence, null, 2),
    );
    console.log(JSON.stringify(evidence));
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  server.close();
  process.exitCode = 1;
});
