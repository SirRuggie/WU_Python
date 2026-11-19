import { readFileSync } from "node:fs";
import { Window } from "happy-dom";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import CwlPageHeader from "./CwlPageHeader";

const styles = [
  "CwlPageHeader.css",
  "HelpButton.css",
  "members/Members.css",
  "ReturnReminderOverview.css",
  "StrikesWorkspace.css",
  "ClanManagement.css",
  "StaffOverview.css",
  "DashboardIssues.css",
].map((file) => readFileSync(`src/${file}`, "utf8"));
const header = renderToStaticMarkup(
  <CwlPageHeader
    title={<h1>Page title</h1>}
    help={<button className="page-help-trigger">Help</button>}
    description="A description with its own bounded text measure."
  />,
);

for (const sharedLast of [false, true]) {
  it(`keeps desktop subtitles on an explicit row with shared CSS ${sharedLast ? "last" : "first"}`, () => {
    const window = new Window({ width: 1440 });
    try {
      const order = sharedLast ? [...styles.slice(1), styles[0]] : styles;
      window.document.head.innerHTML = order
        .map((css) => `<style>${css}</style>`)
        .join("");
      for (const root of [
        "clan-management",
        "ticket-workspace",
        "staff-overview",
        "dashboard-issues",
      ]) {
        window.document.body.innerHTML = `<div class="shell"><main><section class="${root}">${header}</section></main></div>`;
        const title = window.document.querySelector(".cwl-page-header-title")!;
        const description = window.document.querySelector(
          ".cwl-page-header-description",
        )!;
        expect(window.getComputedStyle(title).display).toBe("grid");
        expect(window.getComputedStyle(description).gridColumn).toBe("1 / -1");
        expect(window.getComputedStyle(description).maxWidth).toBe("700px");
      }
    } finally {
      window.happyDOM.abort();
    }
  });
}

it("keeps both phone page identities visible and help available without unclipping the search label", () => {
  const window = new Window({ width: 360 });
  try {
    window.document.head.innerHTML = styles
      .map((css) => `<style>${css}</style>`)
      .join("");
    for (const content of [
      `<section class="members-workspace">${header}<label class="members-search-label">Search members</label></section>`,
      `<section class="server-management">${header}<div><section class="return-overview"></section></div></section>`,
    ]) {
      window.document.body.innerHTML = `<div class="shell"><main>${content}</main></div>`;
      const h1 = window.getComputedStyle(window.document.querySelector("h1")!);
      expect(h1.position).not.toBe("absolute");
      expect(h1.width).not.toBe("1px");
      expect(h1.clipPath).not.toBe("inset(50%)");
      expect(
        window.getComputedStyle(
          window.document.querySelector(".page-help-trigger")!,
        ).display,
      ).not.toBe("none");
    }
    window.document.body.innerHTML = `<label class="members-search-label">Search members</label>`;
    expect(
      window.getComputedStyle(window.document.querySelector("label")!).width,
    ).toBe("1px");
  } finally {
    window.happyDOM.abort();
  }
});

it("places the desktop Strikes title and navigation in full-width successive grid rows", () => {
  const window = new Window({ width: 1440 });
  try {
    window.document.head.innerHTML = styles
      .map((css) => `<style>${css}</style>`)
      .join("");
    window.document.body.innerHTML = `<div class="shell"><main><section class="strikes-workspace strikes-activity-overview">${header}<div class="strikes-navigation"><nav class="strikes-tabs">Tabs</nav></div></section></main></div>`;
    const root = window.document.querySelector(".strikes-workspace")!;
    expect(window.getComputedStyle(root).gridTemplateColumns).toBe(
      "minmax(0, 1fr)",
    );
    for (const child of root.children)
      expect(window.getComputedStyle(child).gridColumn).toBe("1 / -1");
  } finally {
    window.happyDOM.abort();
  }
});
