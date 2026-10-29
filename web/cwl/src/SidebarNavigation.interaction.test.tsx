// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SidebarNavigation, { type DashboardView } from "./SidebarNavigation";

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

it("shows direct overview and moderation links without a staff fold-out", async () => {
  await render("home");
  expect(host.querySelector(".navigation-staff-label")?.textContent).toBe(
    "Staff tools",
  );
  expect(host.querySelector(".navigation-staff-label")?.tagName).toBe("H2");
  expect(host.querySelector("#navigation-staff-tools")).toBeNull();
  const direct = [
    ...host.querySelectorAll<HTMLButtonElement>(
      ".navigation-staff > .navigation-everyday > button",
    ),
  ];
  expect(direct.map((button) => button.textContent)).toEqual([
    "Staff overview",
    "Moderation",
  ]);
  await act(async () => direct[0].click());
  await act(async () => direct[1].click());
  expect(navigate.mock.calls.map(([view]) => view)).toEqual([
    "staff-overview",
    "moderation",
  ]);
});

it("keeps every owner staff group flat", async () => {
  await render("home");
  for (const id of ["cwl", "clans", "members", "bot", "admin"]) {
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
  expect(children("members").hasAttribute("hidden")).toBe(false);
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
    "members",
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
