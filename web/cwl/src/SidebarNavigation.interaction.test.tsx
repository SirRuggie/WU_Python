// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SidebarNavigation, { type DashboardView } from "./SidebarNavigation";
import { dashboardPath, dashboardTarget } from "./dashboardHistory";

let host: HTMLDivElement;
let root: Root;
const navigate = vi.fn();
const props = {
  userId: "staff-nav-test",
  view: "home" as DashboardView,
  canEdit: true,
  isOwner: true,
  permissions: [] as string[],
  onNavigate: navigate,
  season: "",
  publicationStep: "review" as "review" | "announce",
};

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  navigate.mockClear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render(view: DashboardView, extra: Partial<typeof props> = {}) {
  await act(async () =>
    root.render(<SidebarNavigation {...props} {...extra} view={view} />),
  );
}
const toggle = (id: string) =>
  host.querySelector<HTMLButtonElement>(`[aria-controls="navigation-${id}"]`)!;
const children = (id: string) =>
  host.querySelector<HTMLElement>(`#navigation-${id}`)!;

it("shows a direct overview link and groups Members with Moderation", async () => {
  await render("home");
  expect(host.querySelector(".navigation-staff-label")?.textContent).toBe(
    "Staff tools",
  );
  expect(host.querySelector(".navigation-staff-label")?.tagName).toBe("H2");
  expect(host.querySelector("#navigation-staff-tools")).toBeNull();
  const direct = [
    ...host.querySelectorAll<HTMLAnchorElement>(
      ".navigation-staff > .navigation-everyday > a",
    ),
  ];
  expect(direct.map((button) => button.textContent)).toEqual([
    "Staff overview",
  ]);
  await act(async () => direct[0].click());
  await act(async () => toggle("members-moderation").click());
  const grouped = [
    ...children("members-moderation").querySelectorAll<HTMLAnchorElement>("a"),
  ];
  expect(grouped.map((button) => button.textContent)).toEqual([
    "Members",
    "Moderation",
  ]);
  await act(async () => grouped[1].click());
  expect(navigate.mock.calls.map(([view]) => view)).toEqual([
    "staff-overview",
    "moderation",
  ]);
});

it("keeps every owner staff group flat", async () => {
  await render("home");
  for (const id of [
    "cwl",
    "clans",
    "members-moderation",
    "tickets",
    "bot",
    "admin",
  ]) {
    const group = children(id);
    expect(
      group.querySelector(".navigation-children, .strikes-subnav"),
    ).toBeNull();
    expect(group.querySelector("button[aria-controls]")).toBeNull();
  }
});

it("opens the current group on navigation, while allowing collapse on that page", async () => {
  await render("home");
  expect(children("bot").hasAttribute("hidden")).toBe(true);
  await act(async () => toggle("bot").click());
  expect(children("bot").hasAttribute("hidden")).toBe(false);
  await act(async () => toggle("bot").click());
  expect(children("bot").hasAttribute("hidden")).toBe(true);
  await render("image-gallery");
  expect(children("bot").hasAttribute("hidden")).toBe(false);
  await act(async () => toggle("bot").click());
  expect(children("bot").hasAttribute("hidden")).toBe(true);
  await render("image-gallery");
  expect(children("bot").hasAttribute("hidden")).toBe(true);
  await render("roster");
  expect(children("cwl").hasAttribute("hidden")).toBe(false);
  await render("image-gallery");
  expect(children("bot").hasAttribute("hidden")).toBe(false);
});

it("remembers new groups and drops obsolete v3 keys safely", async () => {
  localStorage.setItem(
    "wu-navigation-v3:staff-nav-test",
    JSON.stringify({
      "staff-overview": true,
      "cwl-management": true,
      "cwl-results": true,
      "server-tools": true,
      settings: true,
      tickets: true,
      clans: true,
      members: true,
      bot: false,
    }),
  );
  await render("home");
  expect(children("clans").hasAttribute("hidden")).toBe(false);
  expect(children("members")).toBeNull();
  expect(children("bot").hasAttribute("hidden")).toBe(true);
  const saved = JSON.parse(
    localStorage.getItem("wu-navigation-v3:staff-nav-test")!,
  );
  expect(Object.keys(saved).sort()).toEqual([
    "activity",
    "admin",
    "bot",
    "clans",
    "cwl",
    "members-moderation",
    "my-dashboard",
  ]);
  await act(async () => root.render(<div />));
  await render("home");
  expect(children("clans").hasAttribute("hidden")).toBe(false);
  expect(children("bot").hasAttribute("hidden")).toBe(true);
});

it("does not expose an empty group or unauthorized direct link", async () => {
  await render("home", {
    isOwner: false,
    canEdit: true,
    permissions: ["cwl_roster"],
  });
  expect(toggle("cwl")).not.toBeNull();
  expect(toggle("clans")).toBeNull();
  expect(toggle("members")).toBeNull();
  expect(toggle("bot")).toBeNull();
  expect(toggle("admin")).toBeNull();
  expect(host.textContent).not.toContain("Moderation");
  expect(host.textContent).toContain("Staff overview");
});

it("persists explicit toggles but never an automatic current-group opening", async () => {
  await render("roster");
  expect(children("cwl").hidden).toBe(false);
  const saved = () =>
    JSON.parse(localStorage.getItem("wu-navigation-v3:staff-nav-test")!);
  expect(saved().cwl).toBe(false);
  await render("image-gallery");
  expect(children("bot").hidden).toBe(false);
  expect(saved().bot).toBe(false);
  await act(async () => toggle("clans").click());
  expect(saved().clans).toBe(true);
  expect(saved().bot).toBe(false);
  expect(saved().cwl).toBe(false);
  await act(async () => root.render(<div />));
  await render("home");
  expect(children("cwl").hidden).toBe(true);
  expect(children("bot").hidden).toBe(true);
  expect(children("clans").hidden).toBe(false);
});

it("opens Members with one direct menu link and no extra group toggle", async () => {
  await render("home");
  const links = [...host.querySelectorAll<HTMLAnchorElement>("a")].filter(
    (link) => link.textContent === "Members",
  );
  expect(links).toHaveLength(1);
  expect(links[0].hasAttribute("aria-expanded")).toBe(false);
  await act(async () => links[0].click());
  expect(navigate).toHaveBeenCalledWith("members-settings");
});

it("renders every item as a real link to its route", async () => {
  await render("home");
  for (const id of ["cwl", "clans", "members-moderation", "bot", "admin"])
    if (children(id).hidden) await act(async () => toggle(id).click());
  const links = [...host.querySelectorAll<HTMLAnchorElement>("nav a")];
  expect(links.length).toBeGreaterThan(20);
  for (const link of links) {
    const url = new URL(
      link.getAttribute("href")!,
      "https://dashboard.invalid",
    );
    const target = dashboardTarget(url.search, url.pathname);
    expect(target.view, link.textContent!).toBe(
      link.getAttribute("data-tour-target") === "register" ||
        link.getAttribute("data-tour-target") === "saved"
        ? "signup"
        : link.getAttribute("data-tour-target"),
    );
  }
  const members = links.find((link) => link.textContent === "Members")!;
  expect(members.getAttribute("href")).toBe(
    dashboardPath({ view: "members-settings", season: "" }),
  );
});

it("lets modified clicks through and still navigates on a plain click", async () => {
  await render("home");
  await act(async () => toggle("members-moderation").click());
  const link = [...host.querySelectorAll<HTMLAnchorElement>("nav a")].find(
    (item) => item.textContent === "Members",
  )!;
  const modified = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
    ctrlKey: true,
  });
  await act(async () => link.dispatchEvent(modified));
  expect(modified.defaultPrevented).toBe(false);
  expect(navigate).not.toHaveBeenCalled();
  const plain = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
  });
  await act(async () => link.dispatchEvent(plain));
  expect(plain.defaultPrevented).toBe(true);
  expect(navigate).toHaveBeenCalledWith("members-settings");
});

it("puts the staff season and publication step in every season-page href", async () => {
  await render("home", { season: "7", publicationStep: "announce" });
  await act(async () => toggle("cwl").click());
  const href = (label: string) =>
    [...host.querySelectorAll<HTMLAnchorElement>("nav a")]
      .find((link) => link.textContent === label)
      ?.getAttribute("href");
  expect(href("Build roster")).toBe("/cwl/roster?season=7");
  expect(href("Finalize roster")).toBe("/cwl/publish?step=review&season=7");
  expect(href("Announcements")).toBe("/cwl/publish?step=announce&season=7");
  expect(href("Exports & history")).toBe("/cwl/exports?season=7");
});
