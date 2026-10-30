const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const port = Number(process.argv[2]);
if (!Number.isInteger(port) || port < 8900 || port > 8999)
  throw Error("Expected isolated fixture port");
const origin = `http://127.0.0.1:${port}`;
const output = process.env.WU_AVATAR_SCREENSHOTS || "/tmp/wu-avatar-layout";
fs.mkdirSync(output, { recursive: true });
(async () => {
  const b = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const results = [];
  for (const width of [360, 1440]) {
    const p = await b.newPage({
      viewport: { width, height: width === 360 ? 800 : 1000 },
    });
    const errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    await p.route("**/*", async (r) => {
      if (new URL(r.request().url()).origin !== origin) return r.abort();
      if (
        r.request().url().endsWith("/manage/member-events/settings") &&
        r.request().method() === "GET"
      ) {
        const response = await r.fetch();
        const data = await response.json();
        data.main = { channel_id: null, forum_tag_id: null };
        for (const c of Object.values(data.categories)) c.mode = "main";
        for (const e of Object.values(data.events)) e.channel_id = null;
        return r.fulfill({ response, json: data });
      }
      return r.continue();
    });
    await p.goto(origin + "/server/member-activity");
    await p
      .getByRole("button", { name: "Open local test session", exact: true })
      .click();
    await p.getByRole("button", { name: "Log settings", exact: true }).click();
    await p.getByText("Not posting — no channel set").first().waitFor();
    await p.waitForURL("**/server/moderation");
    const sizes = await p.evaluate(() => ({
      viewport: innerWidth,
      document: document.documentElement.scrollWidth,
    }));
    if (sizes.document > width)
      throw Error("overflow " + JSON.stringify(sizes));
    if (errors.length) throw Error(errors.join("\n"));
    await p.screenshot({
      path: path.join(output, `${width}.png`),
      fullPage: true,
    });
    results.push({ width, url: p.url(), ...sizes, errors });
    await p.close();
  }
  await b.close();
  fs.writeFileSync(
    path.join(output, "browser.json"),
    JSON.stringify(results, null, 2),
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
