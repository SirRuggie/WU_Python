import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import PageEyebrow, { PageGroupContext, pageGroup } from "./PageEyebrow";
import { navigationLabel, navigationSection } from "./SidebarNavigation";

it("names the sidebar group and hides a group that repeats the page name", () => {
  expect(pageGroup("CWL", "Declaration check")).toBe("CWL");
  expect(pageGroup("Tickets", "Tickets")).toBe("");
  expect(pageGroup(undefined, "Dashboard")).toBe("");
  expect(
    pageGroup(navigationSection("declaration"), navigationLabel("declaration")),
  ).toBe("CWL");
  expect(
    pageGroup(navigationSection("tickets"), navigationLabel("tickets")),
  ).toBe("");
});

it("renders the group from context and nothing without one", () => {
  expect(
    renderToStaticMarkup(
      <PageGroupContext.Provider value="Clans">
        <PageEyebrow />
      </PageGroupContext.Provider>,
    ),
  ).toBe('<p class="eyebrow page-eyebrow">Clans</p>');
  expect(renderToStaticMarkup(<PageEyebrow />)).toBe("");
});
