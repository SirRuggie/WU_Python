const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const origin = `http://127.0.0.1:${Number(process.argv[2])}`;
const output =
  process.env.WU_STRIKES_LAYOUT_OUTPUT || "/tmp/wu-strikes-ux-layout";
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  for (const [width, height] of [
    [360, 800],
    [1440, 1000],
  ]) {
    const p = await browser.newPage({ viewport: { width, height } });
    const errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    await p.route("**/*", (r) =>
      new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
    );
    const snap = async (name) => {
      await p.screenshot({ path: path.join(output, `${width}-${name}.png`) });
      const m = await p.evaluate(() => ({
        width: innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        rows: [...document.querySelectorAll(".strike-compact-row")].map(
          (e) => e.getBoundingClientRect().height,
        ),
        small: [...document.querySelectorAll("button,input,select,textarea")]
          .filter(
            (e) =>
              e.checkVisibility() &&
              e.getBoundingClientRect().height > 0 &&
              e.getBoundingClientRect().height < 44,
          )
          .map((e) => ({
            text: e.textContent,
            height: e.getBoundingClientRect().height,
          })),
      }));
      if (m.scrollWidth > width) throw Error("overflow " + name);
      if (m.small.length)
        throw Error("small target " + name + JSON.stringify(m.small));
      const contrast = await p.evaluate(() => {
        const rgb = (s) => (s.match(/[\d.]+/g) || []).map(Number);
        const lum = (c) =>
          c
            .slice(0, 3)
            .map((x) => {
              x /= 255;
              return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
            })
            .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
        const rows = [];
        for (const el of document.querySelectorAll("body *")) {
          if (
            ![...el.childNodes].some(
              (n) => n.nodeType === 3 && n.textContent.trim(),
            ) ||
            !el.checkVisibility() ||
            el.closest(":disabled")
          )
            continue;
          const st = getComputedStyle(el);
          let bg = [0, 0, 0];
          const chain = [];
          for (let n = el; n; n = n.parentElement) chain.unshift(n);
          for (const n of chain) {
            const c = rgb(getComputedStyle(n).backgroundColor);
            const a = c.length === 4 ? c[3] : 1;
            bg = c.slice(0, 3).map((v, i) => v * a + bg[i] * (1 - a));
          }
          const fg = rgb(st.color);
          const L = [lum(fg), lum(bg)].sort((a, b) => b - a);
          rows.push({
            text: el.textContent.trim().slice(0, 50),
            size: parseFloat(st.fontSize),
            ratio: (L[0] + 0.05) / (L[1] + 0.05),
            class: el.className,
          });
        }
        return rows;
      });
      const lowContrast = contrast.filter((row) => row.ratio < 4.5);
      if (lowContrast.length)
        throw Error("contrast " + name + JSON.stringify(lowContrast));
      const fonts = await p.locator(".strikes-workspace").evaluate((root) =>
        [...root.querySelectorAll("*")]
          .filter(
            (el) =>
              el.checkVisibility() &&
              [...el.childNodes].some(
                (n) => n.nodeType === 3 && n.textContent.trim(),
              ),
          )
          .map((el) => ({
            text: el.textContent.trim().slice(0, 60),
            size: parseFloat(getComputedStyle(el).fontSize),
          })),
      );
      if (fonts.some((f) => f.size < 12))
        throw Error(
          "small text " +
            name +
            JSON.stringify(fonts.filter((f) => f.size < 12)),
        );
      results.push({
        width,
        name,
        ...m,
        minimumFont: Math.min(...fonts.map((f) => f.size)),
      });
    };
    await p.goto(origin + "/strikes-preview.html");
    await p.getByRole("button", { name: /CastleFox/ }).waitFor();
    await snap("list");
    await p.getByRole("button", { name: /CastleFox/ }).click();
    await p.locator(".strike-compact-row").first().waitFor();
    await snap("detail");
    await p.getByRole("button", { name: "Next", exact: true }).click();
    await p.getByText("26–28 of 28").waitFor();
    await p.waitForFunction(
      () => document.querySelectorAll(".strike-compact-row").length === 3,
    );
    await p.getByRole("button", { name: "Add strike", exact: true }).click();
    await p
      .getByRole("heading", { name: "Add a strike", exact: true })
      .waitFor();
    await snap("add-player");
    await p
      .getByRole("textbox", { name: /Reason/ })
      .fill("Fixture unsaved reason");
    await p.getByRole("button", { name: "Cancel", exact: true }).click();
    await p.getByRole("dialog").waitFor();
    await snap("cancel");
    await p.getByRole("button", { name: "Discard", exact: true }).click();
    await p.getByRole("button", { name: "← Players", exact: true }).click();
    await p.waitForFunction(
      () =>
        document.activeElement?.getAttribute("data-strike-player") ===
        "#P22ABC",
    );
    await p.getByRole("button", { name: "Add strike", exact: true }).click();
    await p
      .getByRole("heading", { name: "Add a strike", exact: true })
      .waitFor();
    await snap("add-list");
    await p.getByRole("button", { name: "Cancel", exact: true }).click();
    await p.getByRole("button", { name: "Settings", exact: true }).click();
    await p.getByRole("spinbutton").waitFor();
    await snap("settings");
    if (
      await p
        .locator('[aria-label="Available exempt roles"]')
        .innerText()
        .then((t) => t.includes("Managed integration"))
    )
      throw Error("managed shown");
    await p.getByText("Import past wars", { exact: true }).click();
    await p
      .getByRole("button", { name: "Check past wars", exact: true })
      .click();
    await p.getByRole("button", { name: /Add 1 strike/ }).waitFor();
    await snap("import-preview");
    await p.goto(origin + "/strikes-preview.html?settingsConflict=1");
    await p.getByRole("button", { name: "Settings", exact: true }).click();
    await p.getByRole("spinbutton").fill("9");
    await p.getByRole("button", { name: "Save settings", exact: true }).click();
    await p.getByText(/Changed by someone else/).waitFor();
    if ((await p.getByRole("spinbutton").inputValue()) !== "9")
      throw Error("conflict lost edit");
    await snap("settings-conflict");
    if (errors.length) throw Error(errors.join("\n"));
    await p.close();
  }
  fs.writeFileSync(
    path.join(output, "browser-flow.json"),
    JSON.stringify(results, null, 2),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
