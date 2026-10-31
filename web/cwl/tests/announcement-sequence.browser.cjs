const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;
const out = process.env.WU_SEQUENCE_EVIDENCE || "/tmp/wu-announcement-sequence-review";
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 360, height: 800 },
    });
    await context.route("**/*", (r) =>
      new URL(r.request().url()).origin === base ? r.continue() : r.abort(),
    );
    const page = await context.newPage(),
      errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base + "/?view=publication&step=announce&season=1");
    await page.getByRole("button", { name: "Open local test session" }).click();
    if (process.env.WU_SEQUENCE_CAPTURE_ONLY !== "1") {
      await page
        .getByRole("button", { name: "Review and send", exact: true })
        .click();
      const review = page.locator(".announcement-send-review");
      await review.waitFor();
      await page.waitForFunction(
        () =>
          !document
            .querySelector(".announcement-send-review")
            ?.textContent.includes("Loading message preview"),
      );
      await review
        .locator("summary")
        .evaluateAll((nodes) => nodes.forEach((e) => e.click()));
      for (const width of [360, 1440]) {
        await page.setViewportSize({
          width,
          height: width === 360 ? 800 : 1000,
        });
        assert(
          await review.evaluate((e) => e.scrollWidth <= e.clientWidth),
          "review overflow",
        );
        await page.screenshot({ path: `${out}/${width}-confirmation.png` });
      }
      await review
        .getByRole("button", { name: "Queue both announcements" })
        .click();
    }
    let state;
    for (let attempt = 0; attempt < 120; attempt++) {
      state = await (
        await context.request.get(base + "/qa/sequence?check=" + Date.now())
      ).json();
      if (state.posts.length === 12) break;
      await page.waitForTimeout(500);
    }
    assert.equal(state.posts.length, 12);
    fs.writeFileSync(`${out}/sequence.json`, JSON.stringify(state, null, 2));
    console.log(state.posts.map((p) => p.path));
    for (const [channel, names] of [
      ["111111111111111111", ["Alpha 30", "Zulu 30", "Alpha 15", "Zulu 15"]],
      [
        "222222222222222222",
        [
          "W. U. Lazy.128",
          "W. U. Lazy.127",
          "W. U. Lazy.126",
          "W. U. Lazy.125",
        ],
      ],
    ]) {
      const posts = state.posts.filter((p) => p.path.includes(channel));
      assert.equal(posts.length, 6);
      assert.deepEqual(
        posts.slice(1, 5).map((p) => p.payload.content),
        names.map((n) => `**${n}**`),
      );
      assert(posts.slice(1, 5).every((p) => p.images >= 1));
      for (const post of posts.slice(1)) {
        assert.deepEqual(post.payload.allowed_mentions, { parse: [] });
      }
      for (const width of [360, 1440]) {
        await page.setViewportSize({
          width,
          height: width === 360 ? 800 : 1000,
        });
        await page.goto(base + "/qa/channel?channel=" + channel);
        await page.locator("img").first().waitFor();
        await page.waitForFunction(() =>
          [...document.images].every((i) => i.complete && i.naturalWidth),
        );
        await page.screenshot({
          path: `${out}/${width}-${channel}-sequence.png`,
          fullPage: true,
        });
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        );
      }
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(`${out}/sequence.json`, JSON.stringify(state, null, 2));
    console.log(JSON.stringify({ messages: state.posts.length, errors }));
    await context.close();
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
