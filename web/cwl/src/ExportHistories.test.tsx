// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { api, grants } = vi.hoisted(() => ({
  api: vi.fn(),
  grants: new Set<string>(),
}));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: (scope: string) => grants.has(scope),
}));
import ExportWorkspace from "./ExportWorkspace";

const preview = {
  kind: "accounts",
  basis: "current",
  summary: {
    season_label: "November 2026",
    season_status: "draft",
    cwl_month: "2026-11",
    published_version: 1,
    published_at: "2026-11-01T12:00:00Z",
    published_available: true,
  },
  columns: ["player_name"],
  rows: [],
  counts: { rows: 0 },
};
const results = {
  accounts: [
    {
      tag: "#P1",
      player_name: "Old player",
      pool: "main",
      assigned_clan_name: "Family",
      attacks: 4,
      stars: 9,
      notes: "Kept note",
    },
  ],
  publication_version: 1,
};
const raffle = {
  season_status: "draft",
  revision: 1,
  draws: [],
  history: [
    {
      id: 5,
      tag: "#P2",
      player_name: "Medal player",
      clan_name: "Lazy One",
      clan_tag: "#2YQ",
      cycle: "2026-10",
      confirmed_at: "2026-10-31T12:00:00Z",
      voided_at: null,
    },
  ],
};
let host: HTMLDivElement;
let root: Root;
const reads = (needle: string) =>
  api.mock.calls.filter((call) => String(call[0]).includes(needle));
const settle = async () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const disclosure = (text: string) =>
  [...host.querySelectorAll<HTMLDetailsElement>("details")].find((node) =>
    node.querySelector("summary")?.textContent?.startsWith(text),
  )!;
const toggle = async (node: HTMLDetailsElement) => {
  await act(async () => {
    node.open = true;
    node.dispatchEvent(new Event("toggle"));
  });
  await settle();
};
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  grants.clear();
  grants.add("cwl_results");
  grants.add("cwl_bonuses");
  api
    .mockReset()
    .mockImplementation(async (route: string) =>
      route.includes("export-preview")
        ? preview
        : route.includes("bonus-raffle")
          ? raffle
          : results,
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ExportWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
      />,
    ),
  );
  await settle();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("saved histories on Exports", () => {
  it("lists both as closed, read only disclosures and fetches neither", () => {
    expect(disclosure("Saved results history")).toBeTruthy();
    expect(disclosure("Saved bonus history")).toBeTruthy();
    expect(disclosure("Saved results history").open).toBe(false);
    expect(reads("source=history")).toHaveLength(0);
    expect(reads("/bonus-raffle")).toHaveLength(0);
  });
  it("loads results history only when opened", async () => {
    await toggle(disclosure("Saved results history"));
    expect(reads("/participation?source=history")).toHaveLength(1);
    expect(disclosure("Saved results history").textContent).toContain(
      "Old player",
    );
    expect(disclosure("Saved results history").textContent).toContain(
      "Kept note",
    );
    expect(reads("/bonus-raffle")).toHaveLength(0);
  });
  it("loads bonus history only when opened", async () => {
    await toggle(disclosure("Saved bonus history"));
    expect(reads("/bonus-raffle")).toHaveLength(1);
    expect(disclosure("Saved bonus history").textContent).toContain(
      "Medal player",
    );
    expect(disclosure("Saved bonus history").textContent).toContain(
      "not proof medals were awarded",
    );
    expect(reads("source=history")).toHaveLength(0);
  });
  it("writes nothing", async () => {
    await toggle(disclosure("Saved results history"));
    await toggle(disclosure("Saved bonus history"));
    expect(
      api.mock.calls.filter((call) => call[1] && call[1] !== "GET"),
    ).toHaveLength(0);
  });
  it("hides bonus history from staff without a bonus grant", async () => {
    await act(async () => root.render(<></>));
    grants.delete("cwl_bonuses");
    await act(async () =>
      root.render(
        <ExportWorkspace
          seasonId="1"
          seasons={[
            { id: 1, label: "November", status: "draft", signup_open: true },
          ]}
          onSeasonChange={() => {}}
        />,
      ),
    );
    await settle();
    expect(disclosure("Saved results history")).toBeTruthy();
    expect(disclosure("Saved bonus history")).toBeUndefined();
  });
});
