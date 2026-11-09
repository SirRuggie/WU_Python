// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeActivityRoster from "./StrikeActivityRoster";
import type { ActivityAccount } from "./strikeActivityView";
const SLAYER = "100000000000000001",
  ACE = "100000000000000002",
  UNNAMED = "100000000000000003";
const row = (n: number, extra: Partial<ActivityAccount>): ActivityAccount => ({
  player_tag: `#P${String(n).padStart(3, "0")}`,
  player_name: `Account ${String(n).padStart(3, "0")}`,
  current_clan_tag: "#PQQ",
  current_clan_name: "Family",
  town_hall: 14,
  weight: 140000,
  active_strikes: 0,
  total_strikes: 0,
  marked_for_replacement: false,
  status: "active",
  quiet_days: 0,
  last_seen_at: "2026-11-01T12:00:00Z",
  missed_attacks: 0,
  observed_attacks: 0,
  no_attack_wars: 0,
  observed_wars: 3,
  attacked_wars: 3,
  skipped_raid_weekends: 0,
  ...extra,
});
const slayer = { discord_id: SLAYER, discord_name: "slayer" };
const accounts = [
  ...Array.from({ length: 20 }, (_, i) => row(i, slayer)),
  ...Array.from({ length: 10 }, (_, i) =>
    row(100 + i, { discord_id: ACE, discord_name: "ace" }),
  ),
  row(200, { discord_id: UNNAMED }),
  row(201, {}),
  row(202, {
    ...slayer,
    no_attack_wars: 4,
    observed_wars: 5,
    attacked_wars: 1,
    active_strikes: 2,
  }),
];
let host: HTMLDivElement, root: Root;
const profiles = {
  options: [
    { id: SLAYER, display_name: "Slayer Prime", username: "slayer" },
    { id: ACE, display_name: "Ace Prime", username: "ace" },
  ],
};
async function mount(url: string, narrow = false) {
  history.replaceState({}, "", url);
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: narrow && query.includes("899"),
        media: query,
        addEventListener() {},
        removeEventListener() {},
      }) as unknown as MediaQueryList,
  );
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
}
const button = (label: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) =>
      node.textContent === label || node.getAttribute("aria-label") === label,
  )!;
beforeEach(() => {
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
    vi.fn(
      async (input: RequestInfo | URL) =>
        new Response(
          JSON.stringify(
            String(input).includes("/strikes/members")
              ? profiles
              : { accounts, clans: [{ tag: "#PQQ", name: "Family" }] },
          ),
        ),
    ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("shows the member in a table column and never a raw Discord ID", async () => {
  await mount(
    "/strikes?activity_view=all&sort=name&direction=asc&q=Account%2020",
  );
  const headings = [...host.querySelectorAll("th")].map((th) => th.textContent);
  expect(headings).toContain("Member");
  expect(
    [...host.querySelectorAll(".strike-activity-member")].map(
      (node) => node.textContent,
    ),
  ).toEqual(["", "", "@slayer"]);
  expect(host.textContent).not.toContain(SLAYER);
  expect(host.textContent).not.toContain(UNNAMED);
});

it("ends the phone meta line with the member and shows nothing when no name is known", async () => {
  await mount(
    "/strikes?activity_view=all&sort=name&direction=asc&q=Account%2020",
    true,
  );
  const meta = [...host.querySelectorAll(".account-card-meta")].map(
    (node) => node.textContent,
  );
  expect(meta).toEqual([
    "TH14 · Family · 140k",
    "TH14 · Family · 140k",
    "TH14 · Family · 140k · @slayer",
  ]);
  expect(host.textContent).not.toContain(UNNAMED);
});

it("filters by member on the tab, lists every account and removes with its chip", async () => {
  await mount(`/strikes?activity_view=not_attacking&member=${ACE}`);
  expect(host.querySelectorAll("[data-strike-player]")).toHaveLength(10);
  expect(host.querySelector(".strike-activity-rule")!.textContent).toBe(
    "All accounts of @ace",
  );
  expect(
    host.querySelector(".strike-activity-rule")!.hasAttribute("title"),
  ).toBe(false);
  await act(async () => button("Remove Member: @ace").click());
  expect(host.querySelectorAll("[data-strike-player]")).toHaveLength(1);
  expect(host.querySelector(".strike-activity-rule")!.textContent).toBe(
    "3+ wars without attacking",
  );
  expect(location.search).not.toContain("member=");
});

it("searches the Member filter by name and applies the exact ID", async () => {
  await mount("/strikes?activity_view=all");
  await act(async () => button("Filters").click());
  const input = [
    ...document.querySelectorAll<HTMLInputElement>("dialog input"),
  ].find((node) => node.parentElement!.textContent!.startsWith("Find member"))!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "ac");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const option = [
    ...document.querySelectorAll<HTMLButtonElement>("dialog li button"),
  ];
  expect(option.map((node) => node.textContent)).toEqual(["@ace10 accounts"]);
  await act(async () => option[0].click());
  await act(async () => button("Apply filters").click());
  expect(location.search).toContain(`member=${ACE}`);
  expect(host.querySelectorAll("[data-strike-player]")).toHaveLength(10);
});

it("groups by Discord user without splitting a group across pages", async () => {
  await mount("/strikes?activity_view=all&group=discord");
  const headings = () =>
    [...host.querySelectorAll(".strike-group-heading")].map((node) =>
      node.textContent!.replace(/\s+/g, " "),
    );
  // Ace has 10 accounts, slayer 21: 10 + 21 would pass 25, so slayer starts page two.
  expect(headings()).toHaveLength(1);
  expect(headings()[0]).toContain("Ace Prime");
  expect(headings()[0]).toContain("10 accounts");
  expect(host.querySelectorAll("[data-strike-player]")).toHaveLength(10);
  await act(async () => button("Next accounts").click());
  expect(headings()[0]).toContain("Slayer Prime");
  expect(headings()[0]).toContain("21 accounts");
  expect(headings()[0]).toContain("2 active strikes");
  // A linked account with no known name never shows its ID.
  expect(headings()[1]).toContain("Discord member unavailable");
  expect(headings()[2]).toContain("No linked member");
  expect(headings()[2]).toContain("1 account");
  expect(host.querySelectorAll("[data-strike-player]")).toHaveLength(23);
  expect(host.textContent).not.toContain(UNNAMED);
  expect(host.textContent).toContain("11–33 of 33");
});

it("groups by clan from the Sort panel and keeps it in the URL", async () => {
  await mount("/strikes?activity_view=all");
  expect(host.querySelector(".strike-group-heading")).toBeNull();
  await act(async () => button("Sort: Name").click());
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain("Group by");
  expect(
    [...dialog.querySelectorAll(".strike-sort-group button")].map(
      (node) => node.textContent,
    ),
  ).toEqual(["None", "Clan", "Discord user"]);
  await act(async () =>
    [...dialog.querySelectorAll<HTMLButtonElement>(".strike-sort-group button")]
      .find((node) => node.textContent === "Clan")!
      .click(),
  );
  expect(location.search).toContain("group=clan");
  expect(host.querySelector(".strike-group-heading")!.textContent).toContain(
    "Family",
  );
  expect(
    host.querySelector("[title^='Name · Grouped'], .roster-sort-trigger")!
      .textContent,
  ).toContain("Grouped");
});

it("keeps one toolbar row of Search, Sort, Filters and a menu, with the tab rule visible", async () => {
  await mount("/strikes?activity_view=all", true);
  const controls = host.querySelectorAll(
    ".strike-activity-chips button, .strike-activity-toolbar > :is(button, input, select), .strike-activity-toolbar > .strike-activity-sort button, .strike-activity-toolbar > details > summary",
  );
  // Four view chips + Search + Sort + Filters + the menu.
  expect(controls).toHaveLength(8);
  expect(host.querySelector(".strike-activity-toolbar select")).toBeNull();
  expect(host.querySelector('[aria-label^="Ascending order"]')).toBeNull();
  expect(host.querySelector(".strike-activity-rule")!.textContent).toBe(
    "All accounts",
  );
  const groups = [
    ...host.querySelectorAll(".strike-activity-action-menu [role=group]"),
  ];
  expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual([
    "Account",
    "List",
  ]);
  expect(
    [...groups[1].querySelectorAll("button")].map((node) => node.textContent),
  ).toEqual(["Copy list", "Refresh activity"]);
  expect(host.textContent).not.toContain("Help");
});

it("leaves the removed Filters options out of the panel", async () => {
  await mount("/strikes?activity_view=all");
  await act(async () => button("Filters").click());
  const panel = document.querySelector("dialog")!.textContent!;
  expect(panel).not.toContain("Marked for replacement");
  expect(panel).not.toContain("Wars without attacking");
  expect(panel).not.toContain("Quiet days");
  expect(panel).toContain("Include eligible 1–2 strikes");
});
