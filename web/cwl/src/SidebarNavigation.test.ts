import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import DashboardIcon from "./DashboardIcon";
import SidebarNavigation, {
  navigationLabel,
  navigationSection,
  visibleNavigationSections,
} from "./SidebarNavigation";

const memberIds = ["my-dashboard", "activity", "my-cwl"];
const itemsFor = (permissions: string[], canEdit = true, isOwner = false) =>
  visibleNavigationSections(canEdit, isOwner, permissions).flatMap(
    (section) => section.items,
  );
const markup = (
  view: Parameters<typeof SidebarNavigation>[0]["view"],
  permissions: string[] = [],
  isOwner = false,
) =>
  renderToStaticMarkup(
    createElement(SidebarNavigation, {
      userId: "nav-fixture",
      view,
      canEdit: permissions.length > 0 || isOwner,
      isOwner,
      permissions,
      onNavigate: () => {},
    }),
  );

it("keeps member navigation unchanged and hides staff tools without grants", () => {
  const sections = visibleNavigationSections(false, false);
  expect(sections.map((section) => section.id)).toEqual(memberIds);
  expect(
    sections.flatMap((section) => section.items.map((item) => item.view)),
  ).toEqual([
    "home",
    "search",
    "todo",
    "wars",
    "events",
    "signup",
    "signup",
    "assignments",
  ]);
  expect(markup("home")).not.toContain("Staff tools");
});

it("gives roster-only staff one flat CWL group and a direct overview", () => {
  const sections = visibleNavigationSections(true, false, ["cwl_roster"]);
  expect(sections.map((section) => section.id)).toEqual([
    ...memberIds,
    "staff-overview",
    "cwl",
  ]);
  expect(
    sections
      .find((section) => section.id === "cwl")
      ?.items.map((item) => item.label),
  ).toEqual(["Build roster", "Declaration check"]);
  const html = markup("roster", ["cwl_roster"]);
  expect(html).toContain("Staff tools</h2>");
  expect(html).toContain('aria-controls="navigation-cwl"');
  expect(html).toContain('aria-expanded="true"');
  expect(html).not.toContain("navigation-staff-tools");
  expect(html).not.toContain("cwl-results");
});

it("orders all owner destinations in top-level direct links and flat groups", () => {
  const sections = visibleNavigationSections(true, true);
  expect(sections.map((section) => section.id)).toEqual([
    ...memberIds,
    "staff-overview",
    "cwl",
    "moderation",
    "clans",
    "members",
    "bot",
    "admin",
  ]);
  expect(
    sections
      .find((section) => section.id === "cwl")
      ?.items.map((item) => item.label),
  ).toEqual([
    "Seasons",
    "Signup reminders",
    "Build roster",
    "Finalize roster",
    "Announcements",
    "Declaration check",
    "Return reminders",
    "Results & participation",
    "Bonus medals",
    "Exports & history",
  ]);
  expect(
    sections
      .find((section) => section.id === "clans")
      ?.items.map((item) => item.label),
  ).toEqual([
    "Family clans",
    "Clan weights",
    "Strikes",
    "Replacements",
    "FWA tools",
  ]);
  expect(
    sections
      .find((section) => section.id === "members")
      ?.items.map((item) => item.label),
  ).toEqual(["Members & roles", "Tickets", "Ticket settings"]);
  expect(
    sections
      .find((section) => section.id === "bot")
      ?.items.map((item) => item.label),
  ).toEqual(["Command triggers", "Image gallery", "Integrations"]);
  expect(
    sections
      .find((section) => section.id === "admin")
      ?.items.map((item) => item.label),
  ).toEqual(["Staff access", "Dashboard issues"]);
  const destinations = sections.flatMap((section) =>
    section.items.map(
      (item) => `${item.view}:${item.step || item.signupPanel || ""}`,
    ),
  );
  expect(destinations).toHaveLength(33);
  expect(new Set(destinations).size).toBe(destinations.length);
  const html = markup("home", [], true);
  expect(html.indexOf("Staff overview")).toBeLessThan(
    html.indexOf("navigation-cwl"),
  );
  expect(html.indexOf("Moderation")).toBeLessThan(
    html.indexOf("navigation-clans"),
  );
  expect(html).not.toContain("navigation-staff-tools");
  expect(html).not.toContain("cwl-results");
});

it("preserves each permission list and hides empty groups or unauthorized direct links", () => {
  const cases: Array<[string, string[]]> = [
    ["clans", ["clan-management"]],
    ["clan_weights", ["weight-trial"]],
    ["strikes", ["strikes", "replacements"]],
    ["strikes_add", ["strikes", "replacements"]],
    ["strikes_remove", ["strikes", "replacements"]],
    ["member_roles", ["moderation", "members-settings"]],
    ["recruitment", ["applications-settings"]],
    ["tickets", ["tickets", "applications-settings"]],
    ["fwa", ["fwa-settings"]],
    ["text_commands", ["text-commands", "image-gallery"]],
    ["server_tools", ["connections-settings"]],
  ];
  for (const [scope, expected] of cases) {
    const staffViews = visibleNavigationSections(false, false, [scope])
      .filter(
        (section) =>
          !memberIds.includes(section.id) && section.id !== "staff-overview",
      )
      .flatMap((section) => section.items.map((item) => item.view));
    expect(staffViews).toEqual(expected);
  }
  expect(itemsFor(["cwl_roster"]).map((item) => item.view)).not.toContain(
    "publication",
  );
  expect(itemsFor(["cwl_publish"]).map((item) => item.view)).not.toContain(
    "roster",
  );
  expect(itemsFor(["cwl_send"]).map((item) => item.view)).toContain("bonuses");
  expect(itemsFor(["server_tools"]).map((item) => item.view)).not.toContain(
    "moderation",
  );
  expect(
    itemsFor(["cwl_roster"], false).map((item) => item.view),
  ).not.toContain("roster");
  expect(itemsFor(["cwl_roster"]).map((item) => item.view)).not.toContain(
    "access",
  );
});

it("uses the approved labels for menu and page naming", () => {
  expect(navigationLabel("declaration")).toBe("Declaration check");
  expect(navigationLabel("image-gallery")).toBe("Image gallery");
  expect(navigationLabel("tickets")).toBe("Tickets");
  expect(navigationLabel("applications-settings")).toBe("Ticket settings");
  expect(navigationLabel("publication", "announce")).toBe("Announcements");
  expect(navigationSection("applications-settings")).toBe("Members");
  expect(navigationSection("weight-trial")).toBe("Clans");
  expect(navigationSection("moderation")).toBe("Staff tools");
});

it("renders a unique semantic icon beside every member and staff label", () => {
  const sections = visibleNavigationSections(true, true);
  const icons = sections.flatMap((section) => [
    ...(!section.direct ? [section.icon] : []),
    ...section.items.map((item) => item.icon),
  ]);
  const rendered = icons.map((name) =>
    renderToStaticMarkup(createElement(DashboardIcon, { name })),
  );
  expect(new Set(icons).size).toBe(icons.length);
  expect(new Set(rendered).size).toBe(rendered.length);
  expect(icons).toContain("war");
  expect(icons).toContain("fwa");
  expect(icons).not.toContain("tools");
});

it("uses the staff label for direct-link breadcrumbs", () => {
  expect(navigationSection("staff-overview")).toBe("Staff tools");
  expect(navigationSection("moderation")).toBe("Staff tools");
  expect(navigationSection("member-activity")).toBe("Staff tools");
});
