// @vitest-environment happy-dom
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ServerManagement from "./ServerManagement";
import ModerationWorkspace from "./ModerationWorkspace";
import ClanDirectory from "./clanManagement/ClanDirectory";
import SectionTabs from "./SectionTabs";
import FilterChips from "./FilterChips";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
vi.mock("./MemberActivityHistory", () => ({
  default: () => <p>History panel</p>,
}));
vi.mock("./MemberTimeline", () => ({ default: () => <p>Timeline panel</p> }));
vi.mock("./ModerationSettings", () => ({
  default: ({ view }: { view: string }) => <p>Settings panel {view}</p>,
}));

const warMessage = {
  id: "war--win",
  label: "Win message",
  description: "Fictional war copy",
  group: "War",
  endpoint: "/manage/war-win",
  allowed: true,
};
const clanTool = {
  id: "fwa_points",
  label: "Points",
  description: "Fictional clan tool",
  group: "War",
  endpoint: "/manage/points",
  allowed: true,
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.requestAnimationFrame = (callback) =>
    window.setTimeout(() => callback(0), 0);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

const buttonNamed = (name: string) =>
  [...host.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === name,
  )!;

it.each(["fwa-settings", "connections-settings"] as const)(
  "shows the %s index without the removed category row or old catalog",
  async (area) => {
    transport.mockReset().mockImplementation(async (url) => {
      if (url === "/manage") return { sections: [warMessage, clanTool] };
      return {};
    });
    await act(async () => root.render(<ServerManagement area={area} />));
    expect(host.querySelector('[aria-label="Settings categories"]')).toBeNull();
    expect(host.querySelector(".manage-tile, .manage-search")).toBeNull();
    expect(host.querySelector(".server-settings-index")).not.toBeNull();
  },
);

it("marks the open record in a short record list as a navigation item", async () => {
  transport.mockReset().mockImplementation(async (url) => {
    if (url === "/manage") return { sections: [warMessage] };
    if (url === "/manage/war-win")
      return {
        documents: [
          { id: "win-a", label: "Record A", endpoint: "/manage/a" },
          { id: "win-b", label: "Record B", endpoint: "/manage/b" },
        ],
      };
    return {
      revision: 1,
      fields: [{ key: "message", label: "Message", type: "text", value: "" }],
    };
  });
  await act(async () => root.render(<ServerManagement area="fwa-settings" />));
  await act(async () => buttonNamed("Win messageFictional war copy→").click());
  const list = host.querySelector(".manage-section-choices")!;
  expect(list.classList).toContain("nav-list");
  await act(async () => list.querySelector("button")!.click());
  const records = [
    ...host.querySelectorAll(".manage-section-choices > button"),
  ];
  expect(records.map((record) => record.getAttribute("aria-pressed"))).toEqual([
    "true",
    "false",
  ]);
});

it("uses the shared underline tabs for Moderation and keeps both section actions", async () => {
  const route = vi.fn();
  await act(async () =>
    root.render(<ModerationWorkspace memberId="123" onMemberRoute={route} />),
  );
  const group = host.querySelector('[aria-label="Moderation sections"]')!;
  expect(group.getAttribute("role")).toBe("group");
  expect(group.classList).toContain("section-tabs");
  expect(group.classList).toContain("section-tabs--flow");
  expect(group.classList).toContain("moderation-sections");
  expect(host.textContent).toContain("Timeline panel");
  await act(async () => buttonNamed("Activity history").click());
  expect(route).toHaveBeenCalledWith("");
  route.mockClear();
  expect(
    [...group.querySelectorAll("button")].map((node) => node.textContent),
  ).toEqual(["Activity history", "Invites", "Log channels"]);
  await act(async () => buttonNamed("Invites").click());
  expect(buttonNamed("Invites").getAttribute("aria-pressed")).toBe("true");
  expect(host.textContent).toContain("Settings panel invites");
  await act(async () => buttonNamed("Log channels").click());
  expect(buttonNamed("Log channels").getAttribute("aria-pressed")).toBe("true");
  expect(host.textContent).toContain("Settings panel channels");
  expect(host.querySelectorAll("p").length).toBeGreaterThan(0);
  await act(async () => buttonNamed("Activity history").click());
  expect(buttonNamed("Activity history").getAttribute("aria-pressed")).toBe(
    "true",
  );
  expect(route).toHaveBeenCalledWith("");
});

it("marks the selected clan as a navigation item", () => {
  const clan = { tag: "#AAA", name: "Fixture clan", type: "war", logo: "" };
  const html = renderToStaticMarkup(
    <ClanDirectory
      clans={[clan, { ...clan, tag: "#BBB", name: "Other clan" }]}
      types={[]}
      selected={clan}
      query=""
      onQuery={() => {}}
      clanType=""
      onType={() => {}}
      expanded
      onExpanded={() => {}}
      disabled={false}
      loading={false}
      error=""
      onRetry={() => {}}
      onSelect={() => {}}
    />,
  );
  expect(html).toContain('class="clan-directory nav-list"');
  expect(html).toMatch(/aria-pressed="true"[^>]*>.*Fixture clan/);
});

it("fades only the edge of a tab or chip rail that hides items", async () => {
  const widths = vi
    .spyOn(HTMLElement.prototype, "scrollWidth", "get")
    .mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(360);
  await act(async () =>
    root.render(
      <>
        <SectionTabs
          label="Tabs"
          items={[
            { id: "a", label: "A" },
            { id: "b", label: "B" },
          ]}
          value="a"
          onChange={() => {}}
        />
        <FilterChips
          label="Chips"
          value="a"
          options={[{ value: "a", label: "A" }]}
          onChange={() => {}}
        />
      </>,
    ),
  );
  for (const label of ["Tabs", "Chips"]) {
    const rail = host.querySelector(`[aria-label="${label}"]`)!;
    expect(rail.classList).toContain("has-horizontal-fades");
    expect(rail.getAttribute("data-fade-left")).toBe("false");
    expect(rail.getAttribute("data-fade-right")).toBe("true");
  }
  widths.mockReturnValue(360);
  await act(async () => root.render(<></>));
});

it("leaves no solid gold selection or removed tab group in the stylesheets", () => {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.name.endsWith(".css")) files.push(path);
    }
  };
  walk(join(__dirname));
  const css = files.map((file) => readFileSync(file, "utf8")).join("\n");
  for (const removed of [
    "cwl-roster-tabs",
    "member-nav-tabs",
    "signup-panel-tabs",
    "staff-section-menu",
    "bonus-tabs",
    "cwl-workspace-nav",
  ])
    expect(css).not.toContain(removed);
  const rules = css.split("}").map((rule) => rule.split("{"));
  for (const group of [
    "manage-categories",
    "manage-section-choices",
    "clan-directory",
    "moderation-sections",
  ]) {
    const solid = rules.filter(
      ([selector = "", body = ""]) =>
        selector.includes(group) &&
        /background:\s*var\(--wu-accent\)/.test(body),
    );
    expect(solid, group).toEqual([]);
  }
});
