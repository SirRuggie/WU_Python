// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import RosterAssignPanel from "./RosterAssignPanel";
import RosterBalance from "./RosterBalance";
import type { RosterAccount, RosterClan, RosterSnapshot } from "./roster";

const state = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: state.api,
}));
vi.mock("./ActionPanel", () => ({
  default: ({
    children,
    footer,
  }: {
    children: ReactNode;
    footer?: ReactNode;
  }) => (
    <section>
      {children}
      {footer}
    </section>
  ),
}));

const clans = [
  {
    tag: "#X",
    name: "Alpha",
    pool: "main",
    capacity: 15,
    effective_capacity: 15,
    assigned_count: 3,
    archived: false,
  },
  {
    tag: "#Y",
    name: "Bravo",
    pool: "main",
    capacity: 15,
    effective_capacity: 15,
    assigned_count: 2,
    archived: false,
  },
  {
    tag: "#Z",
    name: "Charlie",
    pool: "main",
    capacity: 15,
    effective_capacity: 15,
    assigned_count: 1,
    archived: false,
  },
] as RosterClan[];
const accounts = [
  {
    tag: "#A",
    player_name: "A",
    pool: "main",
    assigned_clan_tag: "#X",
    effective_weight: 2_000_000,
    kept: false,
  },
  {
    tag: "#B",
    player_name: "B",
    pool: "main",
    assigned_clan_tag: "#X",
    effective_weight: null,
    kept: false,
  },
  {
    tag: "#MOVE",
    player_name: "Move",
    pool: "main",
    assigned_clan_tag: "#X",
    effective_weight: 1_000_000,
    kept: false,
  },
  {
    tag: "#C",
    player_name: "C",
    pool: "main",
    assigned_clan_tag: "#Y",
    effective_weight: 2_512_500,
    kept: false,
  },
  {
    tag: "#D",
    player_name: "D",
    pool: "main",
    assigned_clan_tag: "#Y",
    effective_weight: 1_000_000,
    kept: false,
  },
  {
    tag: "#E",
    player_name: "E",
    pool: "main",
    assigned_clan_tag: "#Z",
    effective_weight: null,
    kept: false,
  },
] as RosterAccount[];
const roster = { revision: 7, accounts, clans, undo: null } as RosterSnapshot;

afterEach(() => {
  state.api.mockReset();
  vi.restoreAllMocks();
});

it("renders current known totals and partial/unknown hints in Assign", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <RosterAssignPanel
          roster={roster}
          selectedAccounts={[accounts[2]]}
          hiddenTags={[]}
          busy={false}
          trigger={null}
          onClose={() => {}}
          onAssign={async () => true}
        />,
      ),
    );
    const alpha = [...host.querySelectorAll(".roster-assign-clan")].find(
      (row) => row.textContent?.includes("Alpha"),
    )!;
    const charlie = [...host.querySelectorAll(".roster-assign-clan")].find(
      (row) => row.textContent?.includes("Charlie"),
    )!;
    expect(alpha.textContent).toContain("Current total 3,000k");
    expect(alpha.textContent).toContain("2/3 weighed");
    expect(charlie.textContent).toContain("Current total: no weights yet");
    expect(host.textContent).not.toMatch(/avg\s+(?:\d|—|unknown)/i);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("renders before and projected clan totals in Balance preview", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  state.api.mockImplementation(async (path: string, method?: string) =>
    method === "POST" && path.endsWith("/auto-preview")
      ? {
          revision: 7,
          placements: [{ tag: "#MOVE", assigned_clan_tag: "#Y" }],
          unassigned: [],
        }
      : { published: null },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const button = (label: string) =>
    [...host.querySelectorAll<HTMLButtonElement>("button")].find((item) =>
      item.textContent?.includes(label),
    )!;
  try {
    await act(async () =>
      root.render(
        <RosterBalance
          roster={roster}
          seasonId="1"
          tags={["#MOVE"]}
          trigger={null}
          onClose={() => {}}
          onSaved={async () => {}}
          onBusy={() => {}}
        />,
      ),
    );
    const row = (name: string) =>
      [...host.querySelectorAll(".roster-plan-clan")].find((item) =>
        item.textContent?.includes(name),
      )!;
    expect(row("Alpha").textContent).toContain("Total 3,000k");
    expect(row("Alpha").textContent).toContain("2 of 3 weighed");
    expect(row("Charlie").textContent).toContain("Total: no weights yet");
    await act(async () => {
      row("Alpha")
        .querySelector<HTMLInputElement>('input[type="checkbox"]')!
        .click();
      row("Bravo")
        .querySelector<HTMLInputElement>('input[type="checkbox"]')!
        .click();
    });
    await act(async () => button("Preview placements").click());
    const preview = host.querySelector(".roster-plan-totals")!;
    expect(preview.textContent).toContain("Total 3,000k → 2,000k");
    expect(preview.textContent).toContain("Total 3,512.5k → 4,512.5k");
    expect(preview.textContent).toContain("1 of 2 weighed");
    expect(host.textContent).not.toMatch(/avg\s+(?:\d|—|unknown)/i);
    expect(
      state.api.mock.calls.find((call) => call[1] === "POST")?.[2],
    ).toEqual({
      mode: "balance",
      revision: 7,
      tags: ["#MOVE"],
      clan_tags: ["#X", "#Y"],
      include_locked: false,
    });
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
