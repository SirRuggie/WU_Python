// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({ value: null as any }));
const extraState = vi.hoisted(() => ({
  value: { data: undefined as any, loading: true, error: "", refresh: vi.fn() },
}));
vi.mock("./useDeclarationData", () => ({ default: () => state.value }));
vi.mock("./useDeclarationExtras", () => ({ default: () => extraState.value }));
vi.mock("./DeclarationPingPanel", () => ({
  default: ({
    missing,
    locationStatus,
  }: {
    missing: number;
    locationStatus?: string;
  }) => (
    <div data-ping-count={missing}>
      {locationStatus
        ? locationStatus === "checking"
          ? "Checking locations…"
          : "Locations unavailable"
        : `Ping ${missing} missing`}
    </div>
  ),
}));
import ArrivalCheck from "./ArrivalCheck";
import { staffDetailsEvent } from "./staffDetailsRequest";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const now = Date.now();
function makeData() {
  const accounts = Array.from({ length: 33 }, (_, i) => ({
    tag: `#P000${i}`,
    player_name: `Player ${i}`,
    town_hall: 18,
    pool: "main",
    hosting_pool: "main",
    assigned_clan_tag: i < 16 ? "#A" : "#B",
    assigned_clan_name: i < 16 ? "Amber" : "Blaze",
    user_id: i === 0 ? "" : "505227988229554179",
    current_clan_tag: i === 0 ? "#ELSE" : i < 16 ? "#A" : "#B",
    current_clan_name: i === 0 ? "Elsewhere" : i < 16 ? "Amber" : "Blaze",
    current_clan_checked_at: new Date(now).toISOString(),
    outside_family: i === 0,
  }));
  return {
    arrival: {
      source: "published",
      publication_available: true,
      publication_outdated: false,
      version: 1,
      accounts,
    },
    roster: {
      revision: 1,
      accounts: [],
      clans: [
        { tag: "#A", capacity: 15 },
        { tag: "#B", capacity: 30 },
      ],
    },
    publication: { published: { version: 1 }, last_publication: null },
  };
}
beforeEach(() => {
  extraState.value = {
    data: undefined,
    loading: true,
    error: "",
    refresh: vi.fn(),
  };
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  vi.spyOn(window, "matchMedia").mockImplementation(
    () =>
      ({
        matches: true,
        addEventListener() {},
        removeEventListener() {},
      }) as any,
  );
  Element.prototype.scrollIntoView = vi.fn();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const data = makeData();
  state.value = {
    data,
    records: Object.fromEntries(data.arrival.accounts.map((a) => [a.tag, a])),
    now,
    checkedAt: now,
    refresh: vi.fn(),
    error: "",
    checking: false,
  };
});

it("filters extra-member clans without changing the pool-wide ping count", async () => {
  const accounts = state.value.data.arrival.accounts;
  for (const account of accounts) {
    account.pool = "lazy";
    account.hosting_pool = "lazy";
  }
  state.value.records[accounts[20].tag] = {
    ...state.value.records[accounts[20].tag],
    current_clan_tag: "#ELSE",
    current_clan_name: "Elsewhere",
  };
  const make = (tag: string, name: string, count: number) => ({
    tag,
    name,
    capacity: 15,
    status: "current",
    checked_at: new Date(now).toISOString(),
    count,
    extras: Array.from({ length: count }, (_, i) => ({
      tag: `#V${i}Y`,
      name: `Extra ${i}`,
      town_hall: 16,
      context: "Not signed up",
      assigned_clan_tag: null,
    })),
  });
  extraState.value = {
    data: {
      source: "published",
      basis: 1,
      clans: [make("#A", "Amber", 1), make("#B", "Blaze", 0)],
    },
    loading: false,
    error: "",
    refresh: vi.fn(),
  };
  await render();
  const lazy = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.startsWith("Lazy ·"),
  )!;
  await act(async () => lazy.click());
  expect(toggles()).toHaveLength(2);
  const count = host
    .querySelector("[data-ping-count]")
    ?.getAttribute("data-ping-count");
  expect(count).toBe("2");
  const filter = host.querySelector<HTMLInputElement>(
    ".declaration-extras-filter input",
  )!;
  await act(async () => filter.click());
  expect(toggles()).toHaveLength(1);
  expect(toggles()[0].textContent).toContain("Amber");
  expect(
    host.querySelector("[data-ping-count]")?.getAttribute("data-ping-count"),
  ).toBe(count);
  expect(host.textContent).toContain("1 not on roster");
});

it("renders ordinary roster rows before a slow extra-members read completes", async () => {
  await render();
  expect(toggles()).toHaveLength(2);
  expect(host.textContent).toContain("Checking clan members…");
  expect(host.textContent).not.toContain("0 not on roster");
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
const render = async () =>
  act(async () => root.render(<ArrivalCheck seasonId="1" />));
const toggles = () => [
  ...host.querySelectorAll<HTMLButtonElement>(".declaration-clan-toggle"),
];
it("starts collapsed, counts overfilled ready clans, opens one phone clan and preserves late players", async () => {
  await render();
  expect(host.querySelectorAll(".declaration-player")).toHaveLength(0);
  expect(host.textContent).toContain("1 / 2 clans ready to declare");
  await act(async () => toggles()[0].click());
  expect(host.querySelectorAll(".declaration-player")).toHaveLength(16);
  expect(host.querySelector(".declaration-player")?.className).toContain(
    "missing",
  );
  expect(host.querySelector(".declaration-copy")).toBeNull();
  await act(async () => toggles()[1].click());
  expect(toggles()[0].getAttribute("aria-expanded")).toBe("false");
  expect(host.querySelectorAll(".declaration-player")).toHaveLength(17);
});
it("desktop permits multiple open clans; search opens and highlights a match", async () => {
  vi.mocked(window.matchMedia).mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  } as any);
  await render();
  await act(async () => {
    toggles()[0].click();
    toggles()[1].click();
  });
  expect(host.querySelectorAll(".declaration-player")).toHaveLength(33);
  const input = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Player 20");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.querySelector(".is-match")?.textContent).toContain("Player 20");
});
it.each(["hidden", "never"])(
  "%s has no player list and links to Finalize",
  async (kind) => {
    state.value.data.publication.published = null;
    state.value.data.arrival.publication_available = false;
    if (kind === "hidden")
      state.value.data.publication.last_publication = {
        version: 2,
        published_at: new Date(now).toISOString(),
        withdrawn_at: new Date(now).toISOString(),
      };
    await render();
    expect(host.textContent).toContain(
      kind === "hidden"
        ? "Hidden from members · last published version 2"
        : "Publish the roster first",
    );
    expect(host.querySelectorAll(".declaration-clan")).toHaveLength(0);
    expect(host.querySelector("a")?.getAttribute("href")).toContain(
      "step=review",
    );
  },
);
it("draft changed remains ready; names open read-only snapshot Details with clan order", async () => {
  state.value.data.arrival.publication_outdated = true;
  const open = vi.fn();
  window.addEventListener(staffDetailsEvent, open);
  await render();
  await act(async () => toggles()[0].click());
  const name = host.querySelector<HTMLButtonElement>(".roster-player-name")!;
  await act(async () => name.click());
  const request = (open.mock.calls[0][0] as CustomEvent).detail;
  expect(request.viewOnly).toBe("declaration");
  expect(request.publishedSnapshot.version).toBe(1);
  expect(request.order).toHaveLength(16);
  expect(host.textContent).toContain("1 / 2 clans ready");
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "Details",
    ),
  ).toBe(false);
  window.removeEventListener(staffDetailsEvent, open);
});
it("no result is red, no clan is never Outside family, and no weight or action menu is rendered", async () => {
  const accounts = state.value.data.arrival.accounts;
  delete state.value.records[accounts[0].tag];
  state.value.records[accounts[1].tag] = {
    current_clan_tag: null,
    current_clan_name: null,
    current_clan_checked_at: new Date(now).toISOString(),
    outside_family: true,
  };
  await render();
  await act(async () => toggles()[0].click());
  expect(host.querySelectorAll(".compare-account-missing")).toHaveLength(2);
  expect(host.textContent).toContain("Checking…");
  expect(host.textContent).not.toContain("Outside family");
  expect(host.textContent).not.toContain("No weight");
  expect(host.querySelector('[aria-label^="Actions for"]')).toBeNull();
  expect(
    host.querySelectorAll(".compare-account-arrived .discord-contact"),
  ).toHaveLength(0);
});
it("Copy mentions deduplicates, lists unlinked players and falls back to selectable text", async () => {
  const a = state.value.data.arrival.accounts;
  for (const row of a)
    state.value.records[row.tag] = { ...row, current_clan_tag: "#ELSE" };
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
  });
  await render();
  await act(async () => toggles()[0].click());
  const copy = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === "Copy mentions",
  )!;
  expect(host.textContent).toContain("Can't mention: Player 0");
  await act(async () => copy.click());
  expect(host.querySelector("textarea")?.value).toBe("<@505227988229554179>");
  vi.mocked(navigator.clipboard.writeText).mockResolvedValue();
  await act(async () => copy.click());
  expect(host.textContent).toContain("Copied 1 mentions");
});
it("keeps the draft-changed notice muted without blocking readiness", async () => {
  state.value.data.arrival.publication_outdated = true;
  await render();
  expect(host.querySelector(".declaration-help")?.textContent).toBe(
    "Checking published version 1 · the draft has changes members can't see yet",
  );
  expect(host.textContent).toContain("1 / 2 clans ready to declare");
});
it("excludes awaiting placement from late totals and gives it a neutral section", async () => {
  state.value.data.arrival.accounts[0].assigned_clan_tag = null;
  state.value.data.arrival.accounts[0].assigned_clan_name = null;
  await render();
  expect(host.querySelector(".declaration-summary")?.textContent).toContain(
    "0 players not in their clan",
  );
  expect(host.querySelector(".is-unassigned")?.textContent).toContain(
    "Awaiting placement",
  );
  expect(host.querySelector(".is-unassigned")?.className).not.toContain(
    "is-not-ready",
  );
});
it("keeps readiness help collapsed until explicitly opened", async () => {
  await render();
  expect(host.textContent).not.toContain("Ready = enough");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="About readiness"]')!
      .click(),
  );
  expect(host.textContent).toContain("Ready = enough");
});

it("does not turn pending locations into zero ping or in-clan counts, then shows loaded results", async () => {
  const accounts = state.value.data.arrival.accounts;
  state.value = {
    ...state.value,
    records: {},
    data: {
      ...state.value.data,
      arrival: { ...state.value.data.arrival, updating: true },
    },
  };
  await act(async () => root.render(<ArrivalCheck seasonId="1" />));
  expect(host.textContent).toContain("Checking locations…");
  expect(host.textContent).not.toContain("Ping 0 missing");
  expect(host.textContent).not.toMatch(/0\/(15|30) in clan/);
  expect(host.textContent).not.toContain("needs 30");
  state.value = {
    ...state.value,
    records: Object.fromEntries(accounts.map((a: any) => [a.tag, a])),
    data: {
      ...state.value.data,
      arrival: { ...state.value.data.arrival, updating: false },
    },
  };
  await act(async () => root.render(<ArrivalCheck seasonId="1" />));
  expect(host.textContent).toContain("Ping 1 missing");
  expect(host.textContent).toContain("15/15 in clan");
  expect(host.textContent).not.toContain("Checking locations…");
});

it("keeps confirmed counts during refresh and calls incomplete settled locations unavailable", async () => {
  state.value = { ...state.value, checking: true };
  await act(async () => root.render(<ArrivalCheck seasonId="1" />));
  expect(host.textContent).toContain("Ping 1 missing");
  state.value = {
    ...state.value,
    checking: false,
    records: {},
    data: {
      ...state.value.data,
      arrival: { ...state.value.data.arrival, updating: false },
    },
  };
  await act(async () => root.render(<ArrivalCheck seasonId="1" />));
  expect(host.textContent).toContain("Locations unavailable");
  expect(host.textContent).not.toContain("Ping 0 missing");
  expect(host.textContent).not.toMatch(/0\/(15|30) in clan/);
});

it("uses only the selected pool for Ping availability while another pool is still checking", async () => {
  const accounts = state.value.data.arrival.accounts;
  for (const a of accounts)
    if (a.assigned_clan_tag === "#B") {
      a.pool = "lazy";
      a.hosting_pool = "lazy";
    }
  state.value = {
    ...state.value,
    records: Object.fromEntries(
      accounts
        .filter((a: any) => a.assigned_clan_tag === "#A")
        .map((a: any) => [a.tag, a]),
    ),
    data: {
      ...state.value.data,
      arrival: { ...state.value.data.arrival, updating: true },
    },
  };
  await act(async () => root.render(<ArrivalCheck seasonId="1" />));
  expect(host.querySelector("[data-ping-count]")?.textContent).toBe(
    "Ping 1 missing",
  );
  const lazy = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.startsWith("Lazy ·"),
  )!;
  await act(async () => lazy.click());
  expect(host.querySelector("[data-ping-count]")?.textContent).toBe(
    "Checking locations…",
  );
});

it("offers revision-bound Undo after a declaration filler mark and guards double tap", async () => {
  const { DashboardPermissions } = await import("./DashboardPermissions");
  const transport = vi
    .spyOn(await import("./api"), "api")
    .mockImplementation(async (path: string) =>
      path.includes("roster-filler")
        ? ({
            revision: 2,
            roster_filler: true,
            mark_revision: 1,
            undo: { id: 77, label: "Change filler mark", revision: 2 },
          } as any)
        : ({
            revision: 3,
            tag: "#EXTRA",
            roster_filler: false,
            mark_revision: 2,
          } as any),
    );
  for (const a of state.value.data.arrival.accounts) {
    a.pool = "lazy";
    a.hosting_pool = "lazy";
  }
  extraState.value = {
    loading: false,
    error: "",
    refresh: vi.fn(),
    data: {
      source: "published",
      basis: 1,
      revision: 1,
      clans: [
        {
          tag: "#A",
          name: "Amber",
          capacity: 15,
          status: "current",
          checked_at: new Date(now).toISOString(),
          count: 1,
          extras: [
            {
              tag: "#EXTRA",
              name: "Extra account",
              town_hall: 16,
              context: "Not signed up",
              assigned_clan_tag: null,
              roster_filler: false,
              roster_filler_revision: 0,
            },
          ],
        },
      ],
    },
  };
  localStorage.setItem("wu-staff-cwl-pool", "lazy");
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider
        value={{ owner: false, permissions: ["cwl_roster"] }}
      >
        <ArrivalCheck seasonId="7" />
      </DashboardPermissions.Provider>,
    ),
  );
  const box = host.querySelector<HTMLInputElement>(
    'input[aria-label="Filler: Extra account"]',
  )!;
  expect(box).toBeTruthy();
  await act(async () => box.click());
  expect(host.textContent).toContain("Undo available: Change filler mark");
  const undo = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "Undo",
  )!;
  await act(async () => {
    undo.click();
    undo.click();
  });
  expect(
    transport.mock.calls.filter((c) => c[0].endsWith("/roster/undo")),
  ).toHaveLength(1);
  expect(
    transport.mock.calls.find((c) => c[0].endsWith("/roster/undo"))?.[2],
  ).toEqual({ revision: 2, undo_id: 77 });
  expect(state.value.refresh).not.toHaveBeenCalled();
  expect(extraState.value.refresh).not.toHaveBeenCalled();
});

it("keeps open extra lists and observations while marking five rows without live rechecks", async () => {
  const { DashboardPermissions } = await import("./DashboardPermissions");
  const { patchDeclarationMark } = await import("./declarationMarks");
  const transport = vi.spyOn(await import("./api"), "api");
  let revision = 1;
  transport.mockImplementation(
    async (path: string, _method?: unknown, body?: any) => {
      expect(body.revision).toBe(revision);
      return {
        tag: decodeURIComponent(path.split("/").at(-1)!),
        revision: ++revision,
        roster_filler: true,
        mark_revision: body.mark_revision + 1,
      } as any;
    },
  );
  for (const a of state.value.data.arrival.accounts) {
    a.pool = "lazy";
    a.hosting_pool = "lazy";
  }
  extraState.value = {
    loading: false,
    error: "",
    refresh: vi.fn(),
    data: {
      source: "published",
      basis: 1,
      revision: 1,
      clans: [
        {
          tag: "#A",
          name: "Amber",
          status: "current",
          checked_at: new Date(now).toISOString(),
          capacity: 15,
          count: 5,
          extras: Array.from({ length: 5 }, (_, i) => ({
            tag: `#EXTRA${i}`,
            name: `Extra ${i}`,
            town_hall: 16,
            context: "Not signed up",
            assigned_clan_tag: null,
            assigned_here: false,
          })),
        },
      ],
    },
  };
  (extraState.value as any).applyMark = vi.fn((saved: any) => {
    extraState.value.data = patchDeclarationMark(extraState.value.data, saved);
  });
  localStorage.setItem("wu-staff-cwl-pool", "lazy");
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <ArrivalCheck seasonId="1" />
      </DashboardPermissions.Provider>,
    ),
  );
  const details = host.querySelector<HTMLDetailsElement>(
    ".declaration-extras",
  )!;
  details.open = true;
  for (let i = 0; i < 5; i++) {
    const checkbox = host.querySelector<HTMLInputElement>(
      `input[aria-label="Filler: Extra ${i}"]`,
    )!;
    await act(async () => checkbox.click());
    if (i < 4) {
      expect(host.querySelector(".declaration-extras")).toBe(details);
      expect(details.open).toBe(true);
    }
  }
  expect(transport).toHaveBeenCalledTimes(5);
  expect(state.value.refresh).not.toHaveBeenCalled();
  expect(extraState.value.refresh).not.toHaveBeenCalled();
  expect(extraState.value.data.clans[0].checked_at).toBe(
    new Date(now).toISOString(),
  );
  expect(extraState.value.data.clans[0].count).toBe(0);
});
it("hides marks on archived seasons and Ping uses the shared observed filler location", async () => {
  const { DashboardPermissions } = await import("./DashboardPermissions");
  for (const a of state.value.data.arrival.accounts) {
    a.pool = "lazy";
    a.hosting_pool = "lazy";
  }
  state.value.data.arrival.season_archived = true;
  const account = state.value.data.arrival.accounts[0];
  account.roster_filler = true;
  state.value.records[account.tag] = {
    ...account,
    current_clan_tag: "#OLD",
    current_clan_checked_at: new Date(now - 1000).toISOString(),
  };
  extraState.value = {
    loading: false,
    error: "",
    refresh: vi.fn(),
    data: {
      source: "published",
      basis: 1,
      revision: 1,
      clans: [
        {
          tag: "#A",
          name: "Amber",
          status: "current",
          checked_at: new Date(now).toISOString(),
          capacity: 15,
          count: 1,
          extras: [
            {
              tag: "#E",
              name: "Extra",
              town_hall: 16,
              context: "Not signed up",
              assigned_clan_tag: null,
            },
          ],
          fillers: [
            {
              tag: account.tag,
              name: account.player_name,
              town_hall: 16,
              assigned_here: true,
              roster_filler: true,
            },
          ],
        },
      ],
    },
  };
  localStorage.setItem("wu-staff-cwl-pool", "lazy");
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <ArrivalCheck seasonId="1" />
      </DashboardPermissions.Provider>,
    ),
  );
  expect(host.querySelector('[aria-label^="Filler:"]')).toBeNull();
  expect(
    host.querySelector("[data-ping-count]")?.getAttribute("data-ping-count"),
  ).toBe("0");
});
it("two rapid confirmed marks retain both overlays and send the newest revision next", async () => {
  const { DashboardPermissions } = await import("./DashboardPermissions");
  const { staffDetailsPageEvent } = await import("./useStaffDetailsPage");
  let page: any;
  const capture = (e: Event) => {
    page = (e as CustomEvent).detail;
  };
  window.addEventListener(staffDetailsPageEvent, capture);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <ArrivalCheck seasonId="1" />
        </DashboardPermissions.Provider>,
      ),
    );
    const [a, b] = state.value.data.arrival.accounts;
    await act(async () => {
      page.onFillerChanged({
        tag: a.tag,
        revision: 2,
        roster_filler: true,
        mark_revision: 5,
      });
      page.onFillerChanged({
        tag: b.tag,
        revision: 3,
        roster_filler: true,
        mark_revision: 6,
      });
    });
    const saved = page.publishedSnapshot.roster;
    expect(saved.revision).toBe(3);
    expect(saved.accounts.find((r: any) => r.tag === a.tag)).toMatchObject({
      roster_filler: true,
      roster_filler_revision: 5,
    });
    expect(saved.accounts.find((r: any) => r.tag === b.tag)).toMatchObject({
      roster_filler: true,
      roster_filler_revision: 6,
    });
    expect(state.value.refresh).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener(staffDetailsPageEvent, capture);
  }
});
it("does not offer filler controls without roster permission", async () => {
  localStorage.setItem("wu-staff-cwl-pool", "lazy");
  for (const a of state.value.data.arrival.accounts) {
    a.pool = "lazy";
    a.hosting_pool = "lazy";
  }
  const extrasView = vi.spyOn(await import("./DeclarationExtras"), "default");
  const { DashboardPermissions } = await import("./DashboardPermissions");
  extraState.value = {
    loading: false,
    error: "",
    refresh: vi.fn(),
    data: {
      source: "published",
      basis: 1,
      revision: 1,
      clans: [
        {
          tag: "#A",
          name: "Amber",
          status: "current",
          count: 1,
          extras: [
            {
              tag: "#EX",
              name: "Extra",
              town_hall: 16,
              assigned_clan_tag: null,
            },
          ],
        },
      ],
    },
  };
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider
        value={{ owner: false, permissions: ["cwl_declaration"] }}
      >
        <ArrivalCheck seasonId="1" />
      </DashboardPermissions.Provider>,
    ),
  );
  expect(host.querySelector('[aria-label^="Filler:"]')).toBeNull();
  expect(extrasView).toHaveBeenCalled();
  expect(extrasView.mock.calls.at(-1)?.[0].markControl).toBeUndefined();
  extrasView.mockRestore();
});
