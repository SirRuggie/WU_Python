// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import CompareClans from "./CompareClans";
import { createComparisonMemory } from "./comparisonMemory";
import type { RosterSnapshot } from "./roster";
vi.mock("./useComparisonLocations", () => ({
  useComparisonLocations: () => ({
    records: {},
    checking: true,
    error: "",
    now: 0,
    published: null,
    refresh() {},
  }),
}));
vi.mock("./ActionPanel", () => ({
  default: ({
    children,
    footer,
  }: {
    children: ReactNode;
    footer?: ReactNode;
  }) => (
    <div>
      {children}
      {footer}
    </div>
  ),
}));
it("filters the real Compare view to league Y then sorts without losing chosen league X", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const roster = {
    revision: 1,
    accounts: [],
    clans: [
      {
        tag: "A",
        name: "Zulu",
        pool: "main",
        cwl_league: "Master League I",
        effective_capacity: 15,
      },
      {
        tag: "B",
        name: "Alpha",
        pool: "main",
        cwl_league: "Crystal League I",
        effective_capacity: 15,
      },
    ],
  } as unknown as RosterSnapshot;
  const button = (text: string) =>
    [...document.querySelectorAll("button")].find((e) =>
      e.textContent?.includes(text),
    )!;
  try {
    await act(async () =>
      root.render(
        <CompareClans
          memory={createComparisonMemory()}
          pool="main"
          seasonId="1"
          roster={roster}
          busy={false}
          onEdit={() => {}}
        />,
      ),
    );
    const refresh = host.querySelector<HTMLButtonElement>(
      '.compare-toolbar button[aria-busy="true"]',
    )!;
    expect(host.querySelector('[aria-label="Sort: Weight: high to low"]')).not.toBeNull();
    expect(refresh).not.toBeNull();
    expect(refresh.disabled).toBe(false);
    await act(async () => button("Filters").click());
    const checkbox = [
      ...document.querySelectorAll('input[type="checkbox"]'),
    ].find((e) =>
      e.closest("label")?.textContent?.includes("Crystal League I"),
    ) as HTMLInputElement;
    await act(async () => checkbox.click());
    await act(async () => button("Show 0 players").click());
    expect(document.querySelectorAll(".compare-side")).toHaveLength(1);
    await act(async () => button("Choose clans").click());
    await act(async () => button("Sort chosen clans").click());
    const sort = [...document.querySelectorAll('[role="menuitem"]')].find(
      (e) => e.textContent === "Name A–Z",
    ) as HTMLElement;
    await act(async () => sort.click());
    expect(
      JSON.parse(localStorage.getItem("wu-compare-clans:1:main")!),
    ).toEqual(["B", "A"]);
    await act(async () =>
      (host.querySelector('[aria-label="Sort: Weight: high to low"]') as HTMLButtonElement).click(),
    );
    await act(async () =>
      ([...host.querySelectorAll('[role="menuitem"]')].find((item) =>
        item.textContent?.includes("Town Hall: high to low"),
      ) as HTMLElement).click(),
    );
    expect(host.querySelector('[aria-label="Sort: Town Hall: high to low"]')).not.toBeNull();
    await act(async () =>
      root.render(
        <CompareClans
          memory={createComparisonMemory()}
          pool="lazy"
          seasonId="1"
          roster={roster}
          busy={false}
          onEdit={() => {}}
        />,
      ),
    );
    expect(host.querySelector('[aria-label="Sort: Weight: high to low"]')).not.toBeNull();
  } finally {
    act(() => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
    localStorage.clear();
  }
});
