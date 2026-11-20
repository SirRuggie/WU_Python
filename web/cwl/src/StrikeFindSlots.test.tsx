// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import FindSlots, { type SlotSearch } from "./FindSlots";
import StrikeActivityRoster from "./StrikeActivityRoster";
import { api } from "./api";
import {
  activityFilterQuery,
  parseActivityFilters,
} from "./strikeActivityFilters";
import type { ActivityAccount } from "./strikeActivityView";
import {
  openPicker,
  pickerByLabel,
  typeInPicker,
  clickOption,
} from "./searchPickerTestUtils";
import {
  slotCandidates241,
  slotClans241,
  slotFixtureReply241,
  recruitId241,
} from "../tests/fixtures/slotFixture241";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
let root: Root, host: HTMLDivElement;
const blank: SlotSearch = {
  slotWeights: [],
  slotClans: [],
  slotMember: "",
  slotTownHall: null,
  slotExpanded: {},
};
const rows = slotCandidates241().map((row) => ({
  status: "risk",
  quiet_days: 0,
  missed_attacks: 0,
  observed_attacks: 0,
  no_attack_wars: 0,
  skipped_raid_weekends: 0,
  ...row,
})) as ActivityAccount[];
const slotCalls = () =>
  vi
    .mocked(api)
    .mock.calls.filter(([path]) => path.startsWith("/strikes/replacements"));
const memberCalls = () =>
  vi
    .mocked(api)
    .mock.calls.filter(([path]) => path.startsWith("/strikes/members?query="));
const weights = () =>
  host.querySelector<HTMLInputElement>('input[name="recruit-weights"]')!;
const groups = () => [
  ...host.querySelectorAll<HTMLElement>(".strike-slot-group"),
];
const button = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) =>
      node.textContent?.trim() === name ||
      node.getAttribute("aria-label") === name,
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
async function advance(ms: number) {
  await act(async () => vi.advanceTimersByTimeAsync(ms));
}
async function mount(
  search = blank,
  choose = vi.fn(),
  changed = vi.fn(),
  disabled = false,
) {
  await act(async () =>
    root.render(
      <FindSlots
        clans={slotClans241}
        accounts={[]}
        search={search}
        onSearch={changed}
        onChoose={choose}
        disabled={disabled}
      />,
    ),
  );
  return { choose, changed };
}
async function selectRecruit() {
  const picker = pickerByLabel(host, "Member");
  await openPicker(picker);
  await typeInPicker(picker, "SHOGUN");
  await advance(250);
  await clickOption(picker, "SHOGUN");
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path.startsWith("/strikes/replacements"))
        return slotFixtureReply241(
          new URL(path, "http://fixture").searchParams,
        ) as never;
      if (path.startsWith("/strikes/members?query="))
        return { members: [{ id: recruitId241, name: "SHOGUN" }] } as never;
      if (path.includes("ids=")) return { options: [] } as never;
      if (path.includes("activity=true"))
        return {
          accounts: path.includes("left=true")
            ? [
                {
                  ...rows[0],
                  player_name: "History leaver",
                  left_clan: true,
                  current_clan_tag: null,
                  last_clan_tag: "#PQQ",
                  last_clan_name: "Last clan",
                  departed_at: new Date(
                    Date.now() - 49 * 3600000,
                  ).toISOString(),
                },
              ]
            : rows,
          clans: slotClans241,
        } as never;
      return {} as never;
    });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("shows an inline section with no opener, modal, primary button or automatic empty search", async () => {
  await mount();
  expect(host.querySelector("h2")?.textContent).toBe("Find slots");
  // 241 made this an inline auto-search; 248 must not add a new submit action.
  expect(
    host.querySelectorAll("button.primary, button.is-primary"),
  ).toHaveLength(0);
  expect(
    host.querySelector(
      'dialog, [aria-haspopup="dialog"].strike-find-slots-open',
    ),
  ).toBeNull();
  expect(host.querySelector("button.primary")).toBeNull();
  expect(slotCalls()).toHaveLength(0);
  expect(host.textContent).toContain("Enter weights or select a member");
  const status = host.querySelector('[aria-live="polite"]')!;
  expect(status.classList.contains("sr-only")).toBe(true);
  expect(status.getAttribute("aria-atomic")).toBe("true");
  expect(host.querySelectorAll(".empty-state p")).toHaveLength(1);
});
it("restores legacy weights in order, including duplicates, with TH and expansion", async () => {
  const parsed = parseActivityFilters(
    "?slot_weight=173000&slot_weight=143000&slot_weight=173000&slot_th=18&slot_expanded=w173000:13",
  );
  await mount(parsed);
  expect(weights().value).toBe("173, 143, 173");
  const query = new URL(slotCalls()[0][0], "http://fixture").searchParams;
  expect(query.getAll("weight")).toEqual(["173000", "143000", "173000"]);
  expect(query.get("town_hall")).toBe("18");
  expect(query.get("per_weight")).toBe("13");
  expect(groups()).toHaveLength(3);
  expect(groups()[0].querySelectorAll("li")).toHaveLength(8);
});
it("debounces typing 300ms and puts commas on the text keyboard with linked validation", async () => {
  await mount();
  expect(weights().inputMode).toBe("text");
  await type(weights(), "179, 173");
  await advance(299);
  expect(slotCalls()).toHaveLength(0);
  await advance(1);
  expect(slotCalls()).toHaveLength(1);
  await type(weights(), "bad");
  await advance(300);
  expect(slotCalls()).toHaveLength(1);
  expect(weights().getAttribute("aria-invalid")).toBe("true");
  const error = host.querySelector('[role="alert"]')!;
  expect(weights().getAttribute("aria-describedby")).toContain(error.id);
  expect(error.textContent).toContain("not a weight");
});
it.each(["1,2,3,4,5,6", "501k"])(
  "rejects out-of-contract weights %s without a request",
  async (text) => {
    await mount();
    await type(weights(), text);
    await advance(300);
    expect(slotCalls()).toHaveLength(0);
    expect(weights().getAttribute("aria-invalid")).toBe("true");
  },
);
it("reruns clan and Town Hall selections immediately and keeps removable clan chips", async () => {
  await mount({ ...blank, slotWeights: [179000] });
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  expect(slotCalls()).toHaveLength(2);
  expect(
    new URL(slotCalls()[1][0], "http://fixture").searchParams.getAll("clan"),
  ).toEqual(["#PQQ"]);
  expect(button("Remove Warriors United FWA")).toBeTruthy();
  const hall = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Slot Town Hall"]',
  )!;
  await act(async () => {
    hall.value = "18";
    hall.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(slotCalls().at(-1)![0]).toContain("town_hall=18");
  await act(async () => button("Remove Warriors United FWA").click());
  expect(
    new URL(slotCalls().at(-1)![0], "http://fixture").searchParams.has("clan"),
  ).toBe(false);
});
it("finds a server recruit with no family account, prefills saved weights, and preserves separate equal-weight accounts", async () => {
  await mount();
  expect(memberCalls()).toHaveLength(0);
  await selectRecruit();
  expect(memberCalls()).toHaveLength(1);
  expect(slotCalls()).toHaveLength(1);
  const query = new URL(slotCalls()[0][0], "http://fixture").searchParams;
  expect(query.get("member")).toBe(recruitId241);
  expect(query.has("weight")).toBe(false);
  expect(weights().value).toBe("179, 179, 173, 150, 143");
  expect(groups()).toHaveLength(5);
  expect(host.textContent).toContain("SHOGUN · 179k");
  expect(host.textContent).toContain("Recruit account 2 · 179k");
  expect(host.textContent).toContain("Showing 5 of 6 accounts");
  expect(host.textContent).toContain("No saved weight: Recruit account 7");
  expect(host.textContent).toContain("Linked to two Discord users");
});
it("typed weights win after a member prefill and remain editable", async () => {
  await mount();
  await selectRecruit();
  await type(weights(), "150");
  await advance(300);
  expect(
    new URL(slotCalls().at(-1)![0], "http://fixture").searchParams.getAll(
      "weight",
    ),
  ).toEqual(["150000"]);
  expect(groups()).toHaveLength(1);
});
it("expands one saved group by ten, leaves the equal-weight account at three, and persists stable keys", async () => {
  const changed = vi.fn();
  await mount({ ...blank, slotMember: recruitId241 }, vi.fn(), changed);
  const more =
    groups()[0].querySelector<HTMLButtonElement>(".strike-slot-more")!;
  await act(async () => more.click());
  expect(groups()[0].querySelectorAll("li")).toHaveLength(13);
  expect(groups()[1].querySelectorAll("li")).toHaveLength(3);
  expect(groups()[0].textContent).toContain("13 of 15");
  expect(host.querySelector('[aria-live="polite"]')?.textContent).toBe(
    "13 slots for 179k · 3 slots for 179k · 3 slots for 173k · 3 slots for 150k · 3 slots for 143k",
  );
  expect(
    host.querySelector('[aria-live="polite"]')?.classList.contains("sr-only"),
  ).toBe(false);
  expect(changed.mock.calls.at(-1)![0].slotExpanded).toEqual({
    "a#QVVJG0VR": 13,
  });
  expect(
    new URL(slotCalls().at(-1)![0], "http://fixture").searchParams.get(
      "per_weight",
    ),
  ).toBe("13");
});
it("hides only settled member-notice duplication while loading and input corrections stay visible", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementation((path) =>
    path.startsWith("/strikes/replacements")
      ? (new Promise((resolve) => {
          finish = resolve;
        }) as never)
      : (Promise.resolve({ members: [] }) as never),
  );
  await mount({ ...blank, slotMember: recruitId241 });
  const status = () => host.querySelector('[aria-live="polite"]')!;
  expect(status().textContent).toBe("Updating slots…");
  expect(status().classList.contains("sr-only")).toBe(false);
  await act(async () =>
    finish({ slots: [], member_notice: "No linked accounts" }),
  );
  expect(status().textContent).toBe("No linked accounts");
  expect(status().classList.contains("sr-only")).toBe(true);
  expect(
    host.querySelectorAll(".strike-slot-results .strike-slot-note"),
  ).toHaveLength(1);
  await type(weights(), "bad weight");
  expect(status().textContent).toBe("Enter valid weights to update results.");
  expect(status().classList.contains("sr-only")).toBe(false);
});
it("shows unknown-weight counts, stale-feed and departure labels, with Gap emphasized", async () => {
  await mount({
    ...blank,
    slotWeights: [179000],
    slotExpanded: { w179000: 100 },
  });
  expect(host.textContent).toContain("1 account has no weight");
  expect(host.textContent).toContain("Left clan · 47 h ago");
  expect(host.textContent).toContain("Last seen 2 d ago");
  expect(host.querySelector(".strike-slot-gap b")).toBeTruthy();
  expect(host.querySelector('[aria-live="polite"]')?.textContent).toContain(
    "15 slots for 179k",
  );
});
it("opens details from the full candidate payload even when absent from the roster, keeping search and results", async () => {
  const { choose } = await mount({ ...blank, slotWeights: [179000] });
  const before = groups()[0];
  await act(async () =>
    groups()[0].querySelector<HTMLButtonElement>("li button")!.click(),
  );
  expect(choose).toHaveBeenCalledWith(
    expect.objectContaining({
      player_name: "Slot fixture 1",
      active_strikes: 3,
    }),
  );
  expect(groups()[0]).toBe(before);
  expect(weights().value).toBe("179");
  expect(slotCalls()).toHaveLength(1);
});
it("discards a late response and aborts superseded requests before a filter change completes", async () => {
  let finish!: (value: unknown) => void;
  const original = vi.mocked(api).getMockImplementation()!;
  let first = true;
  vi.mocked(api).mockImplementation((path, ...args) =>
    path.startsWith("/strikes/replacements") && first
      ? ((first = false),
        new Promise((resolve) => {
          finish = resolve;
        }) as never)
      : original(path, ...args),
  );
  await mount({ ...blank, slotWeights: [179000] });
  const signal = slotCalls()[0][3]?.signal;
  await type(weights(), "150");
  expect(signal?.aborted).toBe(true);
  await advance(300);
  const final = host.textContent;
  await act(async () =>
    finish({
      slots: [
        { weight: 1, weight_label: "Late response", total: 0, candidates: [] },
      ],
    }),
  );
  expect(host.textContent).toBe(final);
  expect(host.textContent).not.toContain("Late response");
});
it("keeps old results visibly stale with LoadError on a failed update and retries only the read", async () => {
  await mount({ ...blank, slotWeights: [179000] });
  const old = groups()[0];
  vi.mocked(api).mockRejectedValueOnce(new Error("Fixture unavailable"));
  await type(weights(), "150");
  await advance(300);
  expect(
    host.querySelector(".strike-slot-results")?.classList.contains("is-stale"),
  ).toBe(true);
  expect(groups()[0]).toBe(old);
  expect(host.textContent).toContain("Fixture unavailable");
  expect(
    host.querySelector('[aria-live="polite"]')?.classList.contains("sr-only"),
  ).toBe(false);
  await act(async () => button("Try again").click());
  expect(host.textContent).not.toContain("Fixture unavailable");
  expect(
    vi
      .mocked(api)
      .mock.calls.every(([, method]) => !method || method === "GET"),
  ).toBe(true);
});
it("names a member with no linked accounts without falling back to the generic pool", async () => {
  await mount({ ...blank, slotMember: "241000000000000099" });
  expect(host.textContent).toContain("No linked accounts");
  expect(groups()).toHaveLength(0);
});
it("disabled controls do not start a search or a member request", async () => {
  await mount({ ...blank, slotWeights: [179000] }, vi.fn(), vi.fn(), true);
  expect(slotCalls()).toHaveLength(0);
  expect(memberCalls()).toHaveLength(0);
  expect(weights().disabled).toBe(true);
});
it("restores external query changes without opening a panel or carrying old expansion", async () => {
  await mount({
    ...blank,
    slotWeights: [179000],
    slotExpanded: { w179000: 13 },
  });
  await mount({ ...blank, slotWeights: [150000] });
  expect(weights().value).toBe("150");
  expect(groups()[0].querySelectorAll("li")).toHaveLength(3);
  expect(host.querySelector("dialog")).toBeNull();
});
it("keeps URL state for TH, expansion, saved identities and old slot links", () => {
  const value = parseActivityFilters(
    "?slot_weight=179000&slot_member=241000000000000001&slot_th=18&slot_expanded=w179000:13&slot_expanded=a%23QVVJG0VR:200&slot_expanded=bad:9&slot_expanded=w179000:no",
  );
  expect(value.view).toBe("replacements");
  expect(value.slotTownHall).toBe(18);
  expect(value.slotExpanded).toEqual({ w179000: 13, "a#QVVJG0VR": 100 });
  expect(parseActivityFilters(activityFilterQuery(value))).toEqual(value);
});
it("uses the explicit Left history endpoint, excludes normal clan counts, and retains the default 47-hour grace", async () => {
  history.replaceState({}, "", "/strikes?view=all");
  await act(async () =>
    root.render(<StrikeActivityRoster onChoose={vi.fn()} />),
  );
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([path]) => path === "/strikes/accounts?activity=true"),
  ).toBe(true);
  expect(host.textContent).not.toContain("History leaver");
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.startsWith("Filters"))!
      .click(),
  );
  const membership = document.querySelector<HTMLSelectElement>(
    'dialog select[aria-label="Membership"]',
  )!;
  await act(async () => {
    membership.value = "left";
    membership.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () =>
    [...document.querySelectorAll<HTMLButtonElement>("dialog button")]
      .find((button) => button.textContent === "Apply filters")!
      .click(),
  );
  expect(
    vi
      .mocked(api)
      .mock.calls.some(
        ([path]) => path === "/strikes/accounts?activity=true&left=true",
      ),
  ).toBe(true);
  expect(host.textContent).toContain("History leaver");
  expect(host.textContent).toContain("Last clan");
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.startsWith("Filters"))!
      .click(),
  );
  expect(
    document.querySelector<HTMLSelectElement>(
      'dialog select[aria-label="Clan"]',
    )!.disabled,
  ).toBe(true);
});
it("keeps the same slot section mounted around an inline detail slot", async () => {
  function Harness() {
    const [detail, setDetail] = useState(false);
    return (
      <StrikeActivityRoster
        state="activity_view=replacements&slot_weight=179000"
        onChoose={vi.fn()}
        onSlotChoose={() => setDetail(true)}
        detailSlot={detail ? <p>Fixture account detail</p> : null}
      />
    );
  }
  await act(async () => root.render(<Harness />));
  const section = host.querySelector(".strike-find-slots");
  await act(async () =>
    groups()[0].querySelector<HTMLButtonElement>("li button")!.click(),
  );
  expect(host.textContent).toContain("Fixture account detail");
  expect(host.querySelector(".strike-find-slots")).toBe(section);
  expect(groups()).toHaveLength(1);
});

it("restores member-only saved groups without converting prefill to typed weights", async () => {
  const changed = vi.fn();
  await mount(
    { ...blank, slotMember: recruitId241, slotExpanded: { "a#QVVJG0VR": 13 } },
    vi.fn(),
    changed,
  );
  expect(weights().value).toBe("179, 179, 173, 150, 143");
  expect(
    new URL(slotCalls()[0][0], "http://fixture").searchParams.has("weight"),
  ).toBe(false);
  expect(groups()[0].querySelectorAll("li")).toHaveLength(13);
  expect(groups()[1].querySelectorAll("li")).toHaveLength(3);
  expect(changed).not.toHaveBeenCalled();
});
it("suppresses a closed recruit lookup and discards its late response", async () => {
  let finish!: (value: unknown) => void;
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, ...args) =>
    path.startsWith("/strikes/members?query=")
      ? (new Promise((resolve) => {
          finish = resolve;
        }) as never)
      : original(path, ...args),
  );
  await mount();
  const picker = pickerByLabel(host, "Member");
  await openPicker(picker);
  await typeInPicker(picker, "SHOGUN");
  await advance(250);
  const signal = memberCalls()[0][3]?.signal;
  await act(async () =>
    picker
      .querySelector<HTMLInputElement>('input[role="combobox"]')!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      ),
  );
  expect(signal?.aborted).toBe(true);
  await act(async () =>
    finish({ members: [{ id: recruitId241, name: "Late recruit" }] }),
  );
  expect(host.textContent).not.toContain("Late recruit");
  await advance(1000);
  expect(memberCalls()).toHaveLength(1);
});

it.each([false, true])(
  "renders every missing saved account without repeating a tag (typed=%s)",
  async (typed) => {
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, ...args) => {
      if (!path.startsWith("/strikes/replacements"))
        return original(path, ...args);
      const result = slotFixtureReply241(
        new URL(path, "http://fixture").searchParams,
      );
      return {
        ...result,
        member_accounts: [
          {
            tag: "#P0Y",
            name: "#P0Y",
            saved_weight: null,
            link_disputed: true,
          },
          {
            tag: "#PQL",
            name: "Named recruit",
            saved_weight: null,
            link_disputed: true,
          },
          { tag: "#PQU", name: "Another recruit", saved_weight: null },
        ],
      } as never;
    });
    await mount({
      ...blank,
      slotMember: recruitId241,
      slotWeights: typed ? [179000] : [],
    });
    const notices = [...host.querySelectorAll(".strike-slot-note")].map(
      (node) => node.textContent,
    );
    expect(notices).toContain(
      "No saved weight: #P0Y · Linked to two Discord users",
    );
    expect(notices).toContain(
      "No saved weight: Named recruit #PQL · Linked to two Discord users",
    );
    expect(notices).toContain("No saved weight: Another recruit #PQU");
    expect(host.textContent).not.toContain("#P0Y #P0Y");
  },
);

it("expands only the selected typed occurrence, including legacy expansion fallback and Back restoration", async () => {
  const changed = vi.fn();
  const legacy = {
    ...blank,
    slotWeights: [179000, 179000],
    slotExpanded: { w179000: 13 },
  };
  await mount({ ...blank, slotWeights: [179000, 179000] }, vi.fn(), changed);
  await act(async () =>
    groups()[0].querySelector<HTMLButtonElement>(".strike-slot-more")!.click(),
  );
  expect(groups().map((group) => group.querySelectorAll("li").length)).toEqual([
    13, 3,
  ]);
  expect(changed.mock.calls.at(-1)![0].slotExpanded).toEqual({ w179000o1: 13 });
  await mount(legacy, vi.fn(), changed);
  expect(groups().map((group) => group.querySelectorAll("li").length)).toEqual([
    13, 13,
  ]);
  await act(async () =>
    groups()[0].querySelector<HTMLButtonElement>(".strike-slot-more")!.click(),
  );
  expect(groups().map((group) => group.querySelectorAll("li").length)).toEqual([
    15, 13,
  ]);
  const expanded = changed.mock.calls.at(-1)![0];
  expect(expanded.slotExpanded).toEqual({ w179000: 13, w179000o1: 15 });
  const restored = parseActivityFilters(
    activityFilterQuery({
      ...parseActivityFilters("?activity_view=replacements"),
      ...expanded,
    }),
  );
  await mount(expanded); // Parent echoes onSearch before browser navigation.
  await mount(legacy); // Back to the legacy visit.
  expect(groups().map((group) => group.querySelectorAll("li").length)).toEqual([
    13, 13,
  ]);
  await mount(restored); // Forward to this occurrence's override.
  expect(groups().map((group) => group.querySelectorAll("li").length)).toEqual([
    15, 13,
  ]);
});

it("keeps typed occurrences in input order and validates URL overrides without changing saved keys", async () => {
  const state = parseActivityFilters(
    "?slot_weight=179000&slot_weight=150000&slot_weight=179000&slot_expanded=w179000:3&slot_expanded=w179000o2:13&slot_expanded=w150000o1:999&slot_expanded=w179000o0:13&slot_expanded=w179000o6:13&slot_expanded=w179000o01:13&slot_expanded=w500001o1:13&slot_expanded=w179000o1:-1&slot_expanded=a%23PQQ:1",
  );
  expect(state.slotExpanded).toEqual({
    w179000: 3,
    w179000o2: 13,
    w150000o1: 100,
    "a#PQQ": 3,
  });
  expect(parseActivityFilters(activityFilterQuery(state))).toEqual(state);
  await mount(state);
  expect(groups().map((group) => group.querySelectorAll("li").length)).toEqual([
    3, 15, 13,
  ]);
  expect(weights().value).toBe("179, 150, 179");
});

it.each([false, true])(
  "refreshes the selected 47h/49h partition and ignores late old-mode updates (history=%s)",
  async (initialHistory) => {
    let finishOld!: (result: unknown) => void;
    const calls = new Map<string, number>();
    const normal = {
      ...rows[0],
      player_name: "Grace leaver47",
      left_clan: true,
      departed_at: new Date(Date.now() - 47 * 3600000).toISOString(),
    };
    const left = {
      ...normal,
      player_name: "History leaver49",
      current_clan_tag: null,
      last_clan_name: "Last clan",
      departed_at: new Date(Date.now() - 49 * 3600000).toISOString(),
    };
    vi.mocked(api).mockImplementation(async (path) => {
      if (!path.includes("activity=true")) return { options: [] } as never;
      const history = path.includes("left=true");
      const count = (calls.get(path) ?? 0) + 1;
      calls.set(path, count);
      const payload = {
        accounts: [history ? left : normal],
        clans: slotClans241,
        activity_updating: count === 1,
      };
      if (history === initialHistory && count === 2)
        return new Promise((resolve) => {
          finishOld = resolve;
        }) as never;
      return payload as never;
    });
    const state = (history: boolean) =>
      `activity_view=all${history ? "&left=left" : "&left=all"}`;
    await act(async () =>
      root.render(
        <StrikeActivityRoster
          state={state(initialHistory)}
          onChoose={vi.fn()}
        />,
      ),
    );
    await advance(2000);
    const firstEndpoint = `/strikes/accounts?activity=true${initialHistory ? "&left=true" : ""}`;
    expect(calls.get(firstEndpoint)).toBe(2);
    const oldSignal = vi
      .mocked(api)
      .mock.calls.filter(([path]) => path === firstEndpoint)
      .at(-1)![3]?.signal;
    await act(async () =>
      root.render(
        <StrikeActivityRoster
          state={state(!initialHistory)}
          onChoose={vi.fn()}
        />,
      ),
    );
    expect(oldSignal?.aborted).toBe(true);
    await advance(2000);
    const currentName = initialHistory ? "Grace leaver47" : "History leaver49";
    const oldName = initialHistory ? "History leaver49" : "Grace leaver47";
    expect(host.textContent).toContain(currentName);
    expect(host.textContent).not.toContain(oldName);
    await act(async () =>
      finishOld({
        accounts: [initialHistory ? left : normal],
        clans: slotClans241,
        activity_updating: false,
      }),
    );
    expect(host.textContent).toContain(currentName);
    expect(host.textContent).not.toContain(oldName);
    const selectedEndpoint = `/strikes/accounts?activity=true${!initialHistory ? "&left=true" : ""}`;
    expect(calls.get(selectedEndpoint)).toBe(2); // updating → settled on the same partition.
  },
);
