/* Isolated fixture only. No writes after development login. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2] || 8952);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const results = [],
    errors = [],
    writes = [];
  const output = process.env.WU_TOUR_EVIDENCE;
  if (output) fs.mkdirSync(output, { recursive: true });
  try {
    for (const [width, height] of [
      [360, 800],
      [360, 640],
      [960, 768],
      [1024, 768],
      [1280, 800],
      [1440, 1000],
    ]) {
      const page = await browser.newPage({ viewport: { width, height } });
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.route("**/*", (r) =>
        new URL(r.request().url()).origin === base ? r.continue() : r.abort(),
      );
      await page.goto(base + "/");
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.locator(".tour-card").waitFor();
      page.on("request", (r) => {
        if (!["GET", "HEAD"].includes(r.method()))
          writes.push(r.method() + " " + r.url());
      });
      for (let step = 0; step < 13; step++) {
        if (width === 1440 && step === 1) {
          await page.setViewportSize({ width: 360, height: 800 });
          await page.waitForTimeout(450);
          assert.equal(await page.locator(".sidebar.open").count(), 1);
          await page.setViewportSize({ width, height });
          await page.waitForTimeout(450);
          assert.equal(await page.locator(".sidebar.open").count(), 0);
        }
        await page.waitForTimeout(900);
        await page.locator(".tour-character").evaluate(async (img) => {
          if (!img.complete)
            await new Promise((resolve, reject) => {
              img.onload = resolve;
              img.onerror = reject;
            });
        });
        const measured = await page.evaluate(() => {
          const card = document.querySelector(".tour-card"),
            image = document.querySelector(".tour-character"),
            target = document.querySelector(".tour-spotlight");
          const b = card.getBoundingClientRect(),
            a = image.getBoundingClientRect(),
            t = target?.getBoundingClientRect();
          const scale = Math.min(
            a.width / image.naturalWidth,
            a.height / image.naturalHeight,
          );
          const text = [...card.querySelectorAll("*")].filter((e) =>
            [...e.childNodes].some(
              (n) => n.nodeType === 3 && n.textContent.trim(),
            ),
          );
          return {
            title: document.querySelector("#tour-title").textContent,
            art: image.getAttribute("src"),
            artWidth: image.naturalWidth * scale,
            artHeight: image.naturalHeight * scale,
            wide: card.classList.contains("wide-art"),
            minFont: Math.min(
              ...text.map((e) => parseFloat(getComputedStyle(e).fontSize)),
            ),
            card: {
              top: b.top,
              bottom: b.bottom,
              left: b.left,
              right: b.right,
            },
            target: t
              ? { top: t.top, bottom: t.bottom, left: t.left, right: t.right }
              : null,
            overlap: t
              ? Math.max(
                  0,
                  Math.min(t.right, b.right) - Math.max(t.left, b.left),
                ) *
                Math.max(
                  0,
                  Math.min(t.bottom, b.bottom) - Math.max(t.top, b.top),
                )
              : 0,
            overflow: document.documentElement.scrollWidth > innerWidth,
            notice: !!card.querySelector(".tour-policy"),
            realDisabled: document.querySelector(".tour-real-submit")?.disabled,
          };
        });
        const expectedPath =
          step === 0 || step === 1 || step === 12
            ? "/"
            : step === 2
              ? "/tasks"
              : step === 10
                ? "/my-signups"
                : step === 11
                  ? "/assignments"
                  : "/signup";
        assert.equal(new URL(page.url()).pathname, expectedPath);
        const targetIds = [
          "",
          "home",
          "todo",
          "register",
          "signup-pool",
          "signup-account",
          "signup-review",
          "signup-confirm",
          "",
          "",
          "saved",
          "assignments",
          "",
        ];
        if (targetIds[step]) {
          const real = await page
            .locator(`[data-tour-target="${targetIds[step]}"]`)
            .boundingBox();
          const ring = await page.locator(".tour-spotlight").boundingBox();
          assert(real && ring, `Missing ring at ${width} step ${step}`);
          for (const key of ["x", "y", "width", "height"])
            assert(
              Math.abs(real[key] - ring[key]) <= 2,
              `Ring mismatch ${key} step ${step}`,
            );
        }
        if (step >= 4 && step <= 7) {
          if ([360, 1440].includes(width) && step === 6) {
            const buttons = await page
              .locator(".signup-review-heading button")
              .evaluateAll((items) =>
                items.map((button) => ({
                  visible: button.textContent.trim(),
                  accessible: button.getAttribute("aria-label"),
                  height: button.getBoundingClientRect().height,
                  overflow: button.scrollWidth > button.clientWidth,
                })),
              );
            assert.deepEqual(
              buttons.map(({ visible, accessible }) => [visible, accessible]),
              [
                ["Change CWL", "Change CWL"],
                ["Change accounts", "Change accounts"],
              ],
            );
            assert(
              buttons.every(({ height, overflow }) => height >= 44 && !overflow),
            );
          }
          if ([360, 1440].includes(width) && step === 7) {
            const paragraphs = await page
              .locator(".tour-copy > p")
              .evaluateAll((items) =>
                items.slice(1).map((item) => ({
                  text: item.textContent,
                  top: item.getBoundingClientRect().top,
                  bottom: item.getBoundingClientRect().bottom,
                  bold: item.querySelector("strong")?.textContent,
                })),
              );
            assert.deepEqual(paragraphs.map(({ text }) => text), [
              "When you are ready, tap Sign up.",
              "This is only practice. Nothing is saved now.",
            ]);
            assert.equal(paragraphs[0].bold, "Sign up");
            assert(paragraphs[1].top >= paragraphs[0].bottom);
          }
          const expected = [
            ".pool-choice-grid button[data-tour-target]",
            ".account-card[data-tour-target]",
            ".signup-review.card",
            ".signup-review button.primary",
          ][step - 4];
          assert.equal(
            await page.locator(expected).getAttribute("data-tour-target"),
            targetIds[step],
          );
          const overlapsText = await page.evaluate((selector) => {
            const target = document.querySelector(selector);
            const glove = document
              .querySelector(".tour-glove")
              ?.getBoundingClientRect();
            if (!glove) return false;
            const walker = document.createTreeWalker(
              target,
              NodeFilter.SHOW_TEXT,
            );
            let node;
            while ((node = walker.nextNode())) {
              if (!node.textContent.trim()) continue;
              const range = document.createRange();
              range.selectNodeContents(node);
              for (const rect of range.getClientRects()) {
                if (
                  Math.min(rect.right, glove.right) >
                    Math.max(rect.left, glove.left) &&
                  Math.min(rect.bottom, glove.bottom) >
                    Math.max(rect.top, glove.top)
                )
                  return true;
              }
            }
            return false;
          }, expected);
          assert.equal(
            overlapsText,
            false,
            `Glove overlaps target text: ${width} step ${step}`,
          );
        }
        results.push({ width, height, step, ...measured });
        assert.equal(measured.overlap, 0, JSON.stringify(results.at(-1)));
        assert.equal(measured.overflow, false);
        assert(measured.minFont >= 12);
        assert(
          measured.card.top >= 0 && measured.card.bottom <= height,
          JSON.stringify(results.at(-1)),
        );
        if (measured.wide) {
          assert(measured.artWidth <= 220.1);
          assert(measured.artHeight >= 90);
        } else {
          assert(
            measured.artHeight >= (width <= 900 ? 139.5 : 159.5),
            JSON.stringify(results.at(-1)),
          );
          assert(measured.artWidth <= (width <= 900 ? 140.1 : 160.1));
        }
        assert.equal(measured.notice, false);

        if (
          output &&
          ((width === 360 &&
            height === 800 &&
            [1, 2, 4, 5, 6, 7, 10].includes(step)) ||
            (width === 1440 && [1, 4, 5, 6, 9, 10].includes(step)) ||
            (width === 1024 && step === 4))
        )
          await page.screenshot({
            path: `${output}/${width}-${height}-${step}.jpg`,
            type: "jpeg",
            quality: 80,
          });
        if (step === 7) {
          const title = await page.locator("#tour-title").textContent();
          await page
            .locator('[data-tour-target="signup-confirm"]')
            .evaluate((el) => el.click());
          assert.equal(await page.locator("#tour-title").textContent(), title);
          await page.locator(".tour-spotlight").click();
          assert.equal(await page.locator("#tour-title").textContent(), title);
          assert.equal(await page.locator(".tour-shake").count(), 1);
        }
        await page.locator(".tour-next").click();
      }
      assert.equal(await page.locator(".tour-practice").count(), 0);
      await page.reload();
      await page.waitForTimeout(300);
      assert.equal(await page.locator(".tour-card").count(), 0);
      await page.close();
    }
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    const state = await (await fetch(base + "/qa/state")).json();
    if (state.baseline && state.current)
      assert.deepEqual(state.baseline, state.current);
    console.log(
      JSON.stringify({ results, writes, errors, counts: state }, null, 2),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
