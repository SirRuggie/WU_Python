// @vitest-environment happy-dom
import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeActivityRoster from "./StrikeActivityRoster";
import type { ActivityAccount } from "./strikeActivityView";
import FindSlots from "./FindSlots";
import { parseActivityFilters } from "./strikeActivityFilters";
const viewport = vi.hoisted(() => ({ compact: false }));
vi.mock("./useCompactPreview", () => ({ default: () => viewport.compact }));
const base: ActivityAccount = {
  player_tag: "#PYY",
  player_name: "Filler one",
  current_clan_tag: "#PQQ",
  current_clan_name: "Family",
  town_hall: 14,
  weight: 143000,
  active_strikes: 3,
  total_strikes: 3,
  marked_for_replacement: true,
  status: "risk",
  quiet_days: 2,
  last_seen_at: "2026-11-01T12:00:00Z",
  missed_attacks: 0,
  observed_attacks: 0,
  no_attack_wars: 0,
  observed_wars: 3,
  attacked_wars: 3,
  skipped_raid_weekends: 0,
  discord_id: "100000000000000001",
  discord_name: "slayer",
};
const accounts = [
  base,
  { ...base, player_tag: "#P22", player_name: "Filler two", weight: 173000 },
];
const clans = [
  { tag: "#PQQ", name: "Family", is_fwa: true },
  { tag: "#PRR", name: "Second FWA", is_fwa: true },
  { tag: "#PGG", name: "North", is_fwa: false },
];
const candidate = (account: ActivityAccount, gap: number) => ({
  player_tag: account.player_tag,
  player_name: account.player_name,
  clan_name: "Family",
  weight: account.weight,
  weight_difference: gap,
  town_hall: 14,
  priority: "replace_first",
  active_strikes: 3,
  discord_id: account.discord_id,
  discord_name: account.discord_name,
});
const slotsFor = (url: string) =>
  new URL(url, "http://x").searchParams.getAll("weight").map((value) => ({
    weight: Number(value),
    weight_label: `${Number(value) / 1000}k`,
    candidates:
      Number(value) === 143000
        ? [{ ...candidate(accounts[0], 0), link_disputed: disputedMember }]
        : Number(value) === 999000
          ? []
          : [candidate(accounts[1], 0)],
  }));
let host: HTMLDivElement, root: Root;
let partialMember = false;
let disputedMember = false;
const replacementCalls = () =>
  vi
    .mocked(fetch)
    .mock.calls.map((call) => String(call[0]))
    .filter((url) => url.includes("/strikes/replacements"));
async function mount(url: string, choose = vi.fn()) {
  history.replaceState({}, "", url);
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={choose} />),
  );
  return choose;
}
const button = (label: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) =>
      node.textContent === label || node.getAttribute("aria-label") === label,
  )!;
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
beforeEach(() => {
  viewport.compact = false;
  partialMember = false;
  disputedMember = false;
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
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(
        JSON.stringify(
          url.includes("/strikes/replacements")
            ? {
                slots: slotsFor(url),
                member_partial: url.includes("member=") && partialMember,
              }
            : { accounts, clans },
        ),
      );
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("restores slot parameters from the link and runs the search once", async () => {
  await mount(
    "/strikes?view=replacements&slot_weight=143000&slot_weight=173000&slot_clan=%23PQQ&slot_member=100000000000000001",
  );
  expect(replacementCalls()).toHaveLength(1);
  const url = new URL(replacementCalls()[0], "http://x");
  expect(url.searchParams.getAll("weight")).toEqual(["143000", "173000"]);
  expect(url.searchParams.getAll("clan")).toEqual(["#PQQ"]);
  expect(url.searchParams.get("member")).toBe("100000000000000001");
  expect(
    host.querySelector<HTMLInputElement>(".strike-find-slots input")!.value,
  ).toBe("143, 173");
  expect(
    [...host.querySelectorAll(".strike-slot-group h3")].map(
      (n) => n.textContent,
    ),
  ).toEqual(["143k", "173k"]);
  expect(host.querySelector(".strike-slot-group")!.textContent).toContain(
    "Filler one",
  );
  expect(host.querySelector(".strike-slot-group")!.textContent).toContain(
    "Chopping Block",
  );
  expect(host.querySelector(".strike-slot-group")!.textContent).toContain(
    "@slayer",
  );
  expect(
    host.querySelector(".strike-activity-tabs [aria-pressed=true]")!
      .textContent,
  ).toContain("Replacements");
});

it("notes when some of the member's linked accounts were left out", async () => {
  const link =
    "/strikes?view=replacements&slot_weight=143000&slot_member=100000000000000001";
  await mount(link);
  expect(host.textContent).not.toContain("Some linked accounts were left out.");
  await act(async () => root.render(<></>));
  partialMember = true;
  await mount(link);
  expect(host.textContent).toContain("Some linked accounts were left out.");
});

it("labels a result whose tag is linked to two Discord users", async () => {
  const link = "/strikes?view=replacements&slot_weight=143000";
  await mount(link);
  expect(host.textContent).not.toContain("Linked to two Discord users");
  await act(async () => root.render(<></>));
  disputedMember = true;
  await mount(link);
  expect(host.querySelector(".strike-slot-group")!.textContent).toContain(
    "Linked to two Discord users",
  );
});

it("makes no request while typing and keeps the weights when clans change", async () => {
  await mount("/strikes?activity_view=replacements");
  const input = host.querySelector<HTMLInputElement>(
    ".strike-find-slots input",
  )!;
  await type(input, "143, 173k");
  await type(input, "143, 173k, 150000");
  expect(replacementCalls()).toHaveLength(0);
  await act(async () => button("Find slots").click());
  expect(
    new URL(replacementCalls()[0], "http://x").searchParams.getAll("weight"),
  ).toEqual(["143000", "173000", "150000"]);
  expect(location.search).toContain("slot_weight=143000");
  // Only FWA clans are offered.
  await act(async () => button("Clans: All FWA clans").click());
  const names = [...document.querySelectorAll("dialog label span")].map(
    (node) => node.textContent,
  );
  expect(names).toContain("Second FWA");
  expect(names).not.toContain("North");
  await act(async () =>
    [
      ...document.querySelectorAll<HTMLInputElement>(
        "dialog input[type=checkbox]",
      ),
    ]
      .find((box) => box.parentElement!.textContent!.startsWith("Second FWA"))!
      .click(),
  );
  await act(async () => button("Close").click());
  expect(input.value).toBe("143, 173, 150");
  await act(async () => button("Find slots").click());
  expect(replacementCalls()).toHaveLength(2);
  const second = new URL(replacementCalls()[1], "http://x").searchParams;
  expect(second.getAll("clan")).toEqual(["#PRR"]);
  expect(second.getAll("weight")).toEqual(["143000", "173000", "150000"]);
});

it("names an invalid value, limits to five weights and does not search", async () => {
  await mount("/strikes?activity_view=replacements");
  const input = host.querySelector<HTMLInputElement>(
    ".strike-find-slots input",
  )!;
  await type(input, "143, abc");
  await act(async () => button("Find slots").click());
  expect(
    host.querySelector(".strike-find-slots [role=alert]")!.textContent,
  ).toContain("“abc”");
  await type(input, "1,2,3,4,5,6");
  await act(async () => button("Find slots").click());
  expect(
    host.querySelector(".strike-find-slots [role=alert]")!.textContent,
  ).toBe("Enter up to 5 weights.");
  expect(replacementCalls()).toHaveLength(0);
});

it("shows an empty group message and opens a selected result", async () => {
  const choose = await mount(
    "/strikes?activity_view=replacements&slot_weight=143000&slot_weight=999000",
  );
  const groups = [...host.querySelectorAll(".strike-slot-group")];
  expect(groups[1].textContent).toContain("No slot in these clans.");
  await act(async () =>
    groups[0].querySelector<HTMLButtonElement>("li button")!.click(),
  );
  expect(choose).toHaveBeenCalledOnce();
  expect(choose.mock.calls[0][0].player_tag).toBe("#PYY");
});

it("keeps an FWA clan prefilled by Find a fill for this slot and drops a non-FWA one", async () => {
  // The same query App builds in onFindReplacement, against the backend clan shape.
  const prefill = new URLSearchParams({ activity_view: "replacements" });
  prefill.append("slot_weight", "143000");
  prefill.append("slot_clan", "#PQQ");
  prefill.append("slot_clan", "#PGG");
  await mount(`/strikes?${prefill}`);
  expect(replacementCalls()).toHaveLength(1);
  expect(
    new URL(replacementCalls()[0], "http://x").searchParams.getAll("clan"),
  ).toEqual(["#PQQ"]);
  expect(host.querySelector(".strike-find-slots")!.textContent).toContain(
    "Family",
  );
});

it("opens Replacements with the box restored and no search when a link has no weights", async () => {
  await mount("/strikes?view=replacements&slot_clan=%23PQQ");
  expect(
    host.querySelector(".strike-activity-tabs [aria-pressed=true]")!
      .textContent,
  ).toContain("Replacements");
  expect(host.querySelector(".strike-find-slots")).not.toBeNull();
  expect(replacementCalls()).toHaveLength(0);
  expect(host.querySelector(".strike-find-slots")!.textContent).toContain(
    "Family",
  );
});

it("shows the box only on the Replacements tab", async () => {
  await mount("/strikes?activity_view=all");
  expect(host.querySelector(".strike-find-slots")).toBeNull();
  expect(host.textContent).not.toContain("Match a recruit");
});

it("lays Find slots out as weights plus Find, then clan and member halves", async () => {
  await mount("/strikes?view=replacements");
  const top = host.querySelector(".strike-find-slots-top")!;
  expect(top.querySelector("input")).not.toBeNull();
  expect(top.textContent).toContain("Find slots");
  const row = host.querySelector(".strike-find-slots-row")!;
  expect(
    [...row.children].map((node) => node.getAttribute("aria-label")),
  ).toEqual(["Clans: All FWA clans", "Member: any"]);
});

it("names a result from the account row when the endpoint has no name, never an ID", async () => {
  const bare = (account: ActivityAccount) => ({
    ...candidate(account, 0),
    discord_name: null,
  });
  const rows = [
    accounts[0],
    { ...accounts[1], discord_id: "100000000000000002", discord_name: null },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(
        JSON.stringify(
          url.includes("/strikes/replacements")
            ? {
                slots: [
                  {
                    weight: 143000,
                    weight_label: "143k",
                    candidates: [bare(rows[0]), bare(rows[1])],
                  },
                ],
              }
            : { accounts: rows, clans },
        ),
      );
    }),
  );
  await mount("/strikes?view=replacements&slot_weight=143000");
  const items = [...host.querySelectorAll(".strike-slot-group li")].map(
    (node) => node.textContent!,
  );
  expect(items[0]).toContain("@slayer");
  expect(items[1]).not.toContain("@");
  expect(items[1]).not.toMatch(/\d{15}/);
});

const disclosure = () =>
  host.querySelector<HTMLButtonElement>(".strike-find-slots-toggle")!;
const slotBody = () =>
  host.querySelector<HTMLDivElement>(".strike-find-slots-body")!;
const weights = () =>
  host.querySelector<HTMLInputElement>(".strike-find-slots-top input")!;
const find = () =>
  host.querySelector<HTMLButtonElement>(".strike-find-slots-top button")!;

it("starts on phones with one secondary disclosure and mounted hidden fields, without searching", async () => {
  viewport.compact = true;
  await mount("/strikes?activity_view=replacements");
  expect(disclosure().textContent).toBe("Find slots");
  expect(disclosure().classList.contains("primary")).toBe(false);
  expect(disclosure().getAttribute("aria-expanded")).toBe("false");
  expect(disclosure().getAttribute("aria-controls")).toBe(slotBody().id);
  expect(slotBody().hidden).toBe(true);
  expect(weights().closest("[hidden]")).toBe(slotBody());
  expect(disclosure().querySelector("svg")!.getAttribute("aria-hidden")).toBe(
    "true",
  );
  expect(replacementCalls()).toHaveLength(0);
});

it("opens on a user action, focuses Weights and never requests or changes the URL", async () => {
  viewport.compact = true;
  await mount("/strikes?activity_view=replacements");
  const before = location.href;
  const calls = vi.mocked(fetch).mock.calls.length;
  await act(async () => disclosure().click());
  expect(disclosure().getAttribute("aria-expanded")).toBe("true");
  expect(slotBody().hidden).toBe(false);
  expect(document.activeElement).toBe(weights());
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
  expect(location.href).toBe(before);
});

it("opens a phone URL search once without moving focus and keeps results mounted across collapse", async () => {
  viewport.compact = true;
  const outside = document.createElement("button");
  document.body.append(outside);
  outside.focus();
  await mount(
    "/strikes?view=replacements&slot_weight=143000&slot_weight=173000&slot_weight=150000",
  );
  expect(document.activeElement).toBe(outside);
  expect(disclosure().getAttribute("aria-expanded")).toBe("true");
  expect(replacementCalls()).toHaveLength(1);
  const field = weights();
  const result = host.querySelector(".strike-slot-group");
  const calls = vi.mocked(fetch).mock.calls.length;
  const url = location.href;
  await act(async () => disclosure().click());
  expect(slotBody().hidden).toBe(true);
  expect(disclosure().textContent).toBe("Find slots · 143k, 173k, 150k");
  expect(disclosure().getAttribute("aria-label")).toBe("Find slots, 3 weights");
  await act(async () => disclosure().click());
  expect(weights()).toBe(field);
  expect(field.value).toBe("143, 173, 150");
  expect(host.querySelector(".strike-slot-group")).toBe(result);
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
  expect(location.href).toBe(url);
  outside.remove();
});

it("keeps unsaved weights, clan and member choices while collapsed and across the phone breakpoint", async () => {
  viewport.compact = true;
  const choose = await mount("/strikes?view=replacements");
  await act(async () => disclosure().click());
  await type(weights(), "143, 173k");
  await act(async () => button("Clans: All FWA clans").click());
  await act(async () =>
    [
      ...document.querySelectorAll<HTMLInputElement>(
        "dialog input[type=checkbox]",
      ),
    ]
      .find((box) => box.parentElement!.textContent!.startsWith("Second FWA"))!
      .click(),
  );
  await act(async () => button("Close").click());
  await act(async () => button("Member: any").click());
  await type(
    document.querySelector<HTMLInputElement>(".strike-member-select input")!,
    "slay",
  );
  await act(async () =>
    [
      ...document.querySelectorAll<HTMLButtonElement>(
        ".strike-member-options button",
      ),
    ]
      .find((node) => node.textContent!.includes("@slayer"))!
      .click(),
  );
  const field = weights();
  await act(async () => disclosure().click());
  viewport.compact = false;
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={choose} />),
  );
  expect(disclosure()).toBeNull();
  expect(slotBody().hidden).toBe(false);
  expect(weights()).toBe(field);
  expect(field.value).toBe("143, 173k");
  viewport.compact = true;
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={choose} />),
  );
  expect(slotBody().hidden).toBe(true);
  await act(async () => disclosure().click());
  expect(weights().value).toBe("143, 173k");
  expect(button("Clans: Second FWA")).toBeDefined();
  expect(button("Member: @slayer")).toBeDefined();
  expect(replacementCalls()).toHaveLength(0);
});

it("retains a pending search error received while collapsed and exposes it on expand without retry", async () => {
  viewport.compact = true;
  const normal = vi.mocked(fetch).getMockImplementation()!;
  let release!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/strikes/replacements")
        ? new Promise<Response>((resolve) => {
            release = resolve;
          })
        : normal(input, init),
    ),
  );
  await mount("/strikes?view=replacements&slot_weight=143000");
  expect(find().getAttribute("aria-busy")).toBe("true");
  await act(async () => disclosure().click());
  await act(async () =>
    release(
      new Response(JSON.stringify({ error: "Fixture slots unavailable" }), {
        status: 503,
        headers: { "X-Read-Retries-Exhausted": "1" },
      }),
    ),
  );
  expect(slotBody().hidden).toBe(true);
  expect(slotBody().querySelector("[role=alert]")!.textContent).toContain(
    "Fixture slots unavailable",
  );
  const calls = vi.mocked(fetch).mock.calls.length;
  await act(async () => disclosure().click());
  expect(slotBody().hidden).toBe(false);
  expect(slotBody().querySelector("[role=alert]")!.textContent).toContain(
    "Fixture slots unavailable",
  );
  expect(weights().value).toBe("143");
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
});

function HistorySlots() {
  const [query, setQuery] = useState(location.search);
  useEffect(() => {
    const restore = () => setQuery(location.search);
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  return (
    <FindSlots
      clans={clans}
      accounts={accounts}
      search={parseActivityFilters(query)}
      onSearch={vi.fn()}
      onChoose={vi.fn()}
    />
  );
}

it("reopens Back/Forward URL weights once without focus movement and does not search on disclosure", async () => {
  viewport.compact = true;
  history.replaceState({}, "", "/strikes?view=replacements&slot_weight=143000");
  await act(async () => root.render(<HistorySlots />));
  expect(replacementCalls()).toHaveLength(1);
  await act(async () => disclosure().click());
  expect(disclosure().getAttribute("aria-label")).toBe("Find slots, 1 weight");
  const outside = document.createElement("button");
  document.body.append(outside);
  outside.focus();
  for (const weight of [173000, 143000]) {
    await act(async () => {
      history.replaceState(
        {},
        "",
        `/strikes?view=replacements&slot_weight=${weight}`,
      );
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(slotBody().hidden).toBe(false);
    expect(document.activeElement).toBe(outside);
    expect(weights().value).toBe(String(weight / 1000));
    await act(async () => disclosure().click());
  }
  expect(replacementCalls()).toHaveLength(3);
  outside.remove();
});

it("keeps the desktop box visible with no new disclosure", async () => {
  await mount("/strikes?view=replacements");
  expect(disclosure()).toBeNull();
  expect(slotBody().hidden).toBe(false);
  expect(find().classList.contains("primary")).toBe(true);
});
