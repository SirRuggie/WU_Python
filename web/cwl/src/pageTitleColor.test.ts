import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

// Every page title comes from the shared header, so every title keeps the gold
// ink and the red mark. Pages must not build their own heading block.
const pages = [
  "ServerManagement.tsx",
  "worldClocks/WorldClocksWorkspace.tsx",
  "ModerationWorkspace.tsx",
  "members/MembersPage.tsx",
  "DashboardIssues.tsx",
  "BaseBank.tsx",
  "CommandImageLibrary.tsx",
  "DashboardHome.tsx",
  "TodoWorkspace.tsx",
  "activity/WarsWorkspace.tsx",
  "activity/EventsWorkspace.tsx",
  "DashboardSearch.tsx",
  "StaffOverview.tsx",
  "TicketBrowser.tsx",
  "TextCommands.tsx",
  "ClanManagement.tsx",
  "StrikesWorkspace.tsx",
  "AccessSettings.tsx",
];

it("builds every page title with the shared header", () => {
  for (const page of pages) {
    const source = readFileSync(`src/${page}`, "utf8");
    expect(source, page).toContain("<CwlPageHeader");
    expect(source, page).not.toContain("<PageEyebrow");
  }
});

it("does not override the gold title colour on settings pages", () => {
  const css = readFileSync("src/ServerManagement.css", "utf8");
  expect(css).not.toContain(".manage-heading");
});

it("gives every shared-header title the red title mark", () => {
  const css = readFileSync("src/style.css", "utf8");
  const markRule = css.slice(
    css.indexOf("/* Page titles share the helmet bar"),
  );
  expect(markRule).toContain(".page-head h1");
});
