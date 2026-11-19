import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import CwlPageHeader from "./CwlPageHeader";

it("renders title, help, description below the title, then existing actions", () => {
  const html = renderToStaticMarkup(
    <CwlPageHeader
      title={<h1>Seasons</h1>}
      help={<button className="page-help-trigger">?</button>}
      description="Pick one."
    >
      <button>Refresh</button>
    </CwlPageHeader>,
  );
  const order = [
    "<h1>Seasons</h1>",
    "page-help-trigger",
    'cwl-page-header-description">Pick one.',
    "<button>Refresh</button>",
  ].map((part) => html.indexOf(part));
  expect(order.every((at) => at >= 0)).toBe(true);
  expect([...order].sort((a, b) => a - b)).toEqual(order);
  expect(html).not.toContain("eyebrow");
  expect(html).not.toContain('class="page-head');
  expect(html).toContain('class="cwl-page-header roster-ui');
});

it("omits an empty description and preserves a nested heading level", () => {
  const html = renderToStaticMarkup(
    <CwlPageHeader title={<h2>Clan details</h2>} />,
  );
  expect(html).toContain("<h2>Clan details</h2>");
  expect(html).not.toContain("<h1");
  expect(html).not.toContain("page-eyebrow");
  expect(html).not.toContain("cwl-page-header-description");
});

it("keeps a ReactNode subtitle below the title without flattening its link", () => {
  const html = renderToStaticMarkup(
    <CwlPageHeader
      title={<h1>Family clans</h1>}
      description={<a href="/clans">Clans</a>}
    />,
  );
  expect(html.indexOf("<h1>")).toBeLessThan(
    html.indexOf('class="cwl-page-header-description"'),
  );
  expect(html).toContain('<a href="/clans">Clans</a>');
});

it("stacks the title above its actions at 650px and narrower", () => {
  const css = readFileSync("src/CwlPageHeader.css", "utf8");
  const phone = css.slice(
    css.indexOf("@media (max-width: 650px)"),
    css.indexOf("@media (max-width: 480px)"),
  );
  expect(phone).toMatch(/\.cwl-page-header\s*\{[^}]*flex-wrap:\s*wrap/);
  expect(phone).toMatch(/\.cwl-page-header-title\s*\{[^}]*flex:\s*1 0 100%/);
});

it("moves a season picker to its own row at 480px and narrower", () => {
  const css = readFileSync("src/CwlPageHeader.css", "utf8");
  const narrow = css.slice(css.indexOf("@media (max-width: 480px)"));
  for (const picker of [
    ".participation-season",
    ".bonus-season",
    ".roster-menu",
  ])
    expect(narrow).toMatch(
      new RegExp(`${picker.replace(".", "\\.")}[^{]*\\{[^}]*flex:\\s*1 0 100%`),
    );
});
