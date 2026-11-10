// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeActivityRoster from "./StrikeActivityRoster";
import type { ActivityAccount } from "./strikeActivityView";
const viewport = vi.hoisted(() => ({ compact: true }));
vi.mock("./useCompactPreview", () => ({ default: () => viewport.compact }));
const base: ActivityAccount = {
  player_tag: "#P1",
  player_name: "Alpha",
  current_clan_tag: "#PQQ",
  current_clan_name: "Funnies",
  town_hall: 18,
  weight: 150000,
  active_strikes: 3,
  total_strikes: 3,
  marked_for_replacement: true,
  status: "risk",
  quiet_days: 20,
  last_seen_at: "2026-11-01T12:00:00Z",
  missed_attacks: 0,
  observed_attacks: 0,
  no_attack_wars: 4,
  observed_wars: 5,
  attacked_wars: 1,
  skipped_raid_weekends: 0,
  priority: "high",
};
const accounts: ActivityAccount[] = [
  base,
  { ...base, player_tag: "#P2", player_name: "Bravo", town_hall: 17 },
  {
    ...base,
    player_tag: "#P3",
    player_name: "Charlie",
    current_clan_tag: "#PRR",
    current_clan_name: "Atlas",
    town_hall: 17,
    priority: "replace_first",
  },
];
const clans = [
  { tag: "#PQQ", name: "Funnies" },
  { tag: "#PRR", name: "Atlas" },
];
let host: HTMLDivElement, root: Root;
let release: ((response: Response) => void) | null = null;
const payload = (extra = {}) =>
  new Response(JSON.stringify({ accounts, clans, ...extra }));
async function mount(url: string) {
  history.replaceState({}, "", url);
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
}
const select = (label: string) =>
  host.querySelector<HTMLSelectElement>(`select[aria-label="${label}"]`)!;
const choose = async (node: HTMLSelectElement, value: string) =>
  act(async () => {
    node.value = value;
    node.dispatchEvent(new Event("change", { bubbles: true }));
  });
const params = () => new URLSearchParams(location.search);
const searchButton = () =>
  host.querySelector<HTMLButtonElement>(
    'button[aria-label="Find account or member"]',
  );
const searchField = () =>
  host.querySelector<HTMLInputElement>('input[type="search"]');
beforeEach(() => {
  viewport.compact = true;
  release = null;
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) =>
    setTimeout(() => fn(0), 0),
  );
  vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => payload()),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("phones: one View select with counts replaces the pills and writes activity_view", async () => {
  await mount("/strikes?activity_view=all");
  expect(host.querySelector(".strike-activity-tabs")).toBeNull();
  const view = select("View");
  expect([...view.options].map((option) => option.textContent)).toEqual([
    "Not attacking (3)",
    "Inactive (3)",
    "Replacements (3)",
    "All (3)",
  ]);
  expect(view.value).toBe("all");
  await choose(view, "inactive");
  expect(params().get("activity_view")).toBe("inactive");
  expect(select("View").value).toBe("inactive");
  expect(params().get("quiet")).toBe("14");
});

it("desktop: the four pills are unchanged and there is no View select", async () => {
  viewport.compact = false;
  await mount("/strikes?activity_view=all");
  expect(select("View")).toBeNull();
  expect(
    [...host.querySelectorAll(".strike-activity-tabs button")].map(
      (node) => node.textContent,
    ),
  ).toEqual(["Not attacking 3", "Inactive 3", "Replacements 3", "All 3"]);
});

it("shows … for view counts while activity loads and never a 0", async () => {
  vi.mocked(fetch).mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  await mount("/strikes?activity_view=all");
  expect(
    [...select("View").options].map((option) => option.textContent),
  ).toEqual([
    "Not attacking (…)",
    "Inactive (…)",
    "Replacements (…)",
    "All (…)",
  ]);
  viewport.compact = false;
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  expect(
    [...host.querySelectorAll(".strike-activity-tabs button")].map(
      (node) => node.textContent,
    ),
  ).toEqual(["Not attacking …", "Inactive …", "Replacements …", "All …"]);
  await act(async () => release!(payload()));
  expect(host.querySelector(".strike-activity-tabs")!.textContent).toContain(
    "All 3",
  );
});

it("a failed activity load shows the error and a dash, never a 0", async () => {
  vi.mocked(fetch).mockImplementation(
    async () =>
      new Response(JSON.stringify({ error: "Upstream failed" }), {
        status: 500,
        headers: { "X-Read-Retries-Exhausted": "1" },
      }),
  );
  await mount("/strikes?activity_view=all");
  expect(host.querySelector('[role="alert"]')!.textContent).toContain(
    "Upstream failed",
  );
  const text = [...select("View").options].map((option) => option.textContent);
  expect(text).toEqual([
    "Not attacking (–)",
    "Inactive (–)",
    "Replacements (–)",
    "All (–)",
  ]);
});

it("search sits behind an icon: it opens and focuses the field, × clears and closes", async () => {
  await mount("/strikes?activity_view=all");
  expect(searchField()).toBeNull();
  expect(searchButton()!.getAttribute("aria-expanded")).toBe("false");
  await act(async () => searchButton()!.click());
  expect(searchField()).not.toBeNull();
  expect(document.activeElement).toBe(searchField());
  // The field replaces the toolbar row.
  expect(host.querySelector(".strike-activity-sort")).toBeNull();
  const calls = vi.mocked(fetch).mock.calls.length;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(searchField(), "bra");
    searchField()!.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
  expect(params().get("q")).toBe("bra");
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(1);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label="Clear search"]')!
      .click(),
  );
  expect(searchField()).toBeNull();
  expect(params().get("q")).toBeNull();
  expect(host.querySelector(".strike-activity-sort")).not.toBeNull();
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(3);
});

it("a query in the URL keeps the search field open", async () => {
  await mount("/strikes?activity_view=all&q=alp");
  expect(searchField()!.value).toBe("alp");
  expect(searchButton()).toBeNull();
});

it("Clan and Town Hall selects list A–Z clans and used halls with counts and write one value", async () => {
  await mount("/strikes?activity_view=all");
  const clan = select("Clan");
  expect([...clan.options].map((option) => option.textContent)).toEqual([
    "All clans",
    "Atlas · 1",
    "Funnies · 2",
  ]);
  const hall = select("Town Hall");
  expect([...hall.options].map((option) => option.textContent)).toEqual([
    "Any TH",
    "TH18 · 1",
    "TH17 · 2",
  ]);
  await choose(clan, "#PQQ");
  expect(params().get("clans")).toBe("#PQQ");
  await choose(select("Town Hall"), "17");
  expect(params().get("th")).toBe("17");
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(1);
  await choose(select("Clan"), "");
  await choose(select("Town Hall"), "");
  expect(params().get("clans")).toBeNull();
  expect(params().get("th")).toBeNull();
});

it("old links with 2+ clans or Town Halls show N clans / N Town Halls and keep them until a new selection", async () => {
  await mount("/strikes?activity_view=all&clans=%23PQQ,%23PRR&th=17,18");
  const clan = select("Clan");
  const hall = select("Town Hall");
  expect(clan.selectedOptions[0].textContent).toBe("2 clans");
  expect(clan.selectedOptions[0].disabled).toBe(true);
  expect(hall.selectedOptions[0].textContent).toBe("2 Town Halls");
  expect(hall.selectedOptions[0].disabled).toBe(true);
  expect(host.querySelectorAll(".strike-activity-row")).toHaveLength(3);
  expect(params().get("clans")).toBe("#PQQ,#PRR");
  await choose(clan, "#PRR");
  expect(params().get("clans")).toBe("#PRR");
  expect(params().get("th")).toBe("17,18");
  expect(select("Clan").selectedOptions[0].textContent).toBe("Atlas · 1");
  expect(select("Town Hall").selectedOptions[0].textContent).toBe(
    "2 Town Halls",
  );
});

it("a single clan or Town Hall in the URL is the selected value", async () => {
  await mount("/strikes?activity_view=all&clans=%23PRR&th=18");
  expect(select("Clan").value).toBe("#PRR");
  expect(select("Town Hall").value).toBe("18");
});

const openFilters = async () => {
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((node) => node.textContent === "Filters")!
      .click(),
  );
  return document.querySelector<HTMLElement>("dialog .strike-activity-more")!;
};

it("the Filters panel has no clan or Town Hall controls and keeps the decided order", async () => {
  await mount("/strikes?activity_view=all");
  const more = await openFilters();
  const text = document.querySelector("dialog")!.textContent!;
  expect(text).not.toContain("Find clan");
  expect(text).not.toContain("Town halls");
  expect(text).not.toMatch(/\bClans\b/);
  const heading = (node: Element) =>
    node.matches(".strike-filter-priority")
      ? "Priority"
      : node.matches(".strike-member-select")
        ? "Member"
        : node.matches(".strike-filter-weights")
          ? "Weight"
          : node.querySelector("input[type=checkbox]")
            ? `Checkbox: ${node.textContent}`
            : node.firstChild!.textContent!.trim();
  expect([...more.children].map(heading)).toEqual([
    "Priority",
    "Strikes",
    "Raid weekends without attacking",
    "Member",
    "Weight",
    "Membership",
    "Checkbox: Include eligible 1–2 strikes",
    "Checkbox: No activity yet",
  ]);
  const weight = more.querySelector(".strike-filter-weights")!;
  expect(weight.querySelectorAll("input[type=number]")).toHaveLength(2);
});

it("Priority is four chips with counts and stays multi-select", async () => {
  await mount("/strikes?activity_view=all");
  const more = await openFilters();
  const chips = [
    ...more.querySelectorAll<HTMLButtonElement>(
      ".strike-filter-priority button",
    ),
  ];
  expect(chips.map((chip) => chip.textContent)).toEqual([
    "Chopping block 1",
    "High 2",
    "Normal 0",
    "None 0",
  ]);
  await act(async () => chips[0].click());
  await act(async () => chips[1].click());
  expect(chips.map((chip) => chip.getAttribute("aria-pressed"))).toEqual([
    "true",
    "true",
    "false",
    "false",
  ]);
  await act(async () =>
    [...document.querySelectorAll<HTMLButtonElement>("dialog button")]
      .find((node) => node.textContent === "Apply filters")!
      .click(),
  );
  expect(params().get("priority")).toBe("high,replace_first");
  const again = await openFilters();
  await act(async () =>
    again
      .querySelectorAll<HTMLButtonElement>(".strike-filter-priority button")[0]
      .click(),
  );
  expect(
    again
      .querySelectorAll(".strike-filter-priority button")[1]
      .getAttribute("aria-pressed"),
  ).toBe("true");
});
