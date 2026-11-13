import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import CwlPageHeader from "./CwlPageHeader";
import { PageGroupContext } from "./PageEyebrow";

const render = (header: React.ReactElement, group = "CWL") =>
  renderToStaticMarkup(
    <PageGroupContext.Provider value={group}>
      {header}
    </PageGroupContext.Provider>,
  );

it("renders eyebrow, title, help, description and actions in order", () => {
  const html = render(
    <CwlPageHeader
      title={<h1>Seasons</h1>}
      help={<button className="page-help-trigger">?</button>}
      description="Pick one."
    >
      <button>Refresh</button>
    </CwlPageHeader>,
  );
  const order = [
    'class="eyebrow page-eyebrow">CWL',
    "<h1>Seasons</h1>",
    "page-help-trigger",
    'cwl-page-header-description">Pick one.',
    "<button>Refresh</button>",
  ].map((part) => html.indexOf(part));
  expect(order.every((at) => at >= 0)).toBe(true);
  expect([...order].sort((a, b) => a - b)).toEqual(order);
  expect(html).toContain("page-head cwl-page-header");
});

it("leaves out the eyebrow when asked and omits an empty description", () => {
  const html = render(
    <CwlPageHeader eyebrow={false} title={<h1>Hey, Sam</h1>} />,
  );
  expect(html).not.toContain("page-eyebrow");
  expect(html).not.toContain("cwl-page-header-description");
});

it("stacks the title above its actions at 650px and narrower", () => {
  const css = readFileSync("src/CwlPageHeader.css", "utf8");
  const phone = css.slice(
    css.indexOf("@media (max-width: 650px)"),
    css.indexOf("@media (max-width: 480px)"),
  );
  expect(phone).toMatch(
    /\.page-head\.cwl-page-header\s*\{[^}]*flex-wrap:\s*wrap/,
  );
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
