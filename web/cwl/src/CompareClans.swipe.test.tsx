// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CompareClans from "./CompareClans";
import { createComparisonMemory } from "./comparisonMemory";
import type { RosterSnapshot } from "./roster";
import { swipeEvent } from "./swipeTestEvents";
vi.mock("./useComparisonLocations", () => ({
  useComparisonLocations: () => ({
    records: {},
    checking: false,
    error: "",
    now: 0,
    published: [],
    checkedAt: 0,
    refresh: vi.fn(),
  }),
}));
vi.mock("./CompareClanHeader", () => ({
  default: ({ clan }: { clan: { name: string } }) => <span>{clan.name}</span>,
}));
vi.mock("./ComparePlayerCard", () => ({
  default: ({ onDetails }: { onDetails: () => void }) => (
    <button onClick={onDetails}>Details</button>
  ),
}));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const edit = vi.fn();
const roster = {
  revision: 1,
  clans: ["Alpha", "Beta", "Gamma"].map((name, i) => ({
    name,
    tag: `#CLAN${i}`,
    pool: "main",
    archived: false,
  })),
  accounts: [0, 1, 2].map((i) => ({
    tag: `#PLAYER${i}`,
    player_name: `Player${i}`,
    assigned_clan_tag: `#CLAN${i}`,
    user_id: "123",
    pool: "main",
    town_hall: 19,
    effective_weight: 190000,
  })),
} as unknown as RosterSnapshot;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  edit.mockReset();
  vi.stubGlobal("innerWidth", 360);
  vi.stubGlobal("visualViewport", { scale: 1 });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const current = () =>
  host.querySelector<HTMLElement>(".mobile-current .compare-player-list")!;
const selected = () =>
  host.querySelector('.compare-mobile-card[aria-pressed="true"]')?.textContent;
it("swipes the player list between clans with no wrap and consumes one click on the newly focused list", async () => {
  await act(async () =>
    root.render(
      <CompareClans
        memory={createComparisonMemory()}
        pool="main"
        seasonId="1"
        roster={roster}
        busy={false}
        onEdit={edit}
      />,
    ),
  );
  expect(selected()).toBe("Alpha");
  await act(async () => {
    swipeEvent(current());
  });
  expect(selected()).toBe("Beta");
  await act(async () => current().querySelector("button")!.click());
  expect(edit).not.toHaveBeenCalled();
  await act(async () => current().querySelector("button")!.click());
  expect(edit).toHaveBeenCalledExactlyOnceWith("#PLAYER1");
  await act(async () => {
    swipeEvent(current());
  });
  expect(selected()).toBe("Gamma");
  await act(async () => {
    swipeEvent(current());
  });
  expect(selected()).toBe("Gamma");
  await act(async () => {
    swipeEvent(current(), 100, 250);
  });
  expect(selected()).toBe("Beta");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label="Previous clan"]')!
      .click(),
  );
  expect(selected()).toBe("Alpha");
  await act(async () => {
    swipeEvent(current(), 100, 250);
  });
  expect(selected()).toBe("Alpha");
  await act(async () =>
    host.querySelectorAll<HTMLButtonElement>(".compare-mobile-card")[2].click(),
  );
  expect(selected()).toBe("Gamma");
});
it("retains edge guards in the Compare consumer", async () => {
  await act(async () =>
    root.render(
      <CompareClans
        memory={createComparisonMemory()}
        pool="main"
        seasonId="1"
        roster={roster}
        busy={false}
        onEdit={edit}
      />,
    ),
  );
  await act(async () => {
    swipeEvent(current(), 23, 200);
  });
  expect(selected()).toBe("Alpha");
});
