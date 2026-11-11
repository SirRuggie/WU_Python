// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { it, expect, vi } from "vitest";
import BonusWorkspace from "./BonusWorkspace";
import ParticipationWorkspace from "./ParticipationWorkspace";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api,
}));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
const account = {
  tag: "#PYY",
  player_name: "Fixture",
  pool: "main",
  assigned_clan_tag: "#PQQ",
  assigned_clan_name: "Family",
  town_hall: 16,
  attacks: 3,
  stars: 9,
  notes: "",
  revision: 1,
  in_latest_publication: true,
  source_status: "ready",
  source_complete: true,
};
const data = {
  season_status: "draft",
  cycle: "2026-11",
  revision: 1,
  policies: { main: 3, lazy: null },
  policy: {},
  clans: [{ tag: "#PQQ", name: "Family", slots: null }],
  accounts: [account],
  draws: [],
  history: [],
  cycle_confirmed: [],
  active_other_cycles: [],
  sync: { enabled: false, warning: null, last_checked_at: null },
  publication_version: 1,
};
// Prompt 228: Bonus selects a clan card (prompt 229: no clan selected shows cards only); Results uses the short-list select.
async function selectCurrent(host: HTMLElement) {
  const card = host.querySelector<HTMLButtonElement>(
    '.bonus-clan-card[aria-pressed="true"]',
  );
  if (card) {
    await act(async () => card.click());
    return;
  }
  const select = host.querySelector<HTMLSelectElement>('select[name="clan"]')!;
  expect(select).not.toBeNull();
  await act(async () => {
    select.value = select.value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
for (const workspace of ["Bonus", "Participation"]) {
  it(`${workspace} keeps the current hosting-clan selection without resetting work`, async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    localStorage.clear();
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function () {
      this.open = false;
    };
    api.mockReset();
    api.mockResolvedValue(data);
    if (!window.confirm) window.confirm = () => true;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          workspace === "Bonus" ? (
            <BonusWorkspace
              seasonId="1"
              seasons={[]}
              urlState="pool=main&clan=%23PQQ"
              onSeasonChange={() => {}}
            />
          ) : (
            <ParticipationWorkspace
              seasonId="1"
              seasons={[]}
              onSeasonChange={() => {}}
            />
          ),
        ),
      );
      let input: HTMLInputElement | null = null;
      if (workspace === "Bonus") {
        expect(host.querySelector(".bonus-context strong")?.textContent).toBe(
          "November 2026",
        );
        await act(async () =>
          host
            .querySelector<HTMLInputElement>(
              '.bonus-check input[type="checkbox"]',
            )!
            .click(),
        );
        input = host.querySelector<HTMLInputElement>(
          '.bonus-flow input[type="number"]',
        );
        expect(input).not.toBeNull();
        await act(async () => {
          Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype,
            "value",
          )!.set!.call(input, "3");
          input!.dispatchEvent(new Event("input", { bubbles: true }));
        });
      }
      const before = api.mock.calls.length;
      await selectCurrent(host);
      expect(confirm).not.toHaveBeenCalled();
      expect(api.mock.calls).toHaveLength(before);
      if (input)
        expect(
          host.querySelector<HTMLInputElement>(
            '.bonus-flow input[type="number"]',
          )?.value,
        ).toBe("3");
      expect(document.querySelector("dialog[open]")).toBeNull();
    } finally {
      await act(async () => root.unmount());
      host.remove();
      confirm.mockRestore();
    }
  });
}
