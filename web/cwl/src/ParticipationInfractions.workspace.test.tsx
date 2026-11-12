// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./useDiscordIdentities", () => ({
  default: () => ({ members: {}, loading: false }),
}));
import { DashboardPermissions } from "./DashboardPermissions";
import ParticipationWorkspace from "./ParticipationWorkspace";

const row = (tag: string, name: string) => ({
  tag,
  player_name: name,
  town_hall: 16,
  pool: "lazy",
  assigned_clan_tag: "#2YQ",
  assigned_clan_name: "Lazy One",
  attacks: 4,
  stars: 9,
  notes: "",
  revision: 1,
  updated_by: null,
  updated_at: null,
  in_latest_publication: true,
  source_status: "complete",
  source_complete: true,
});
const participation = {
  publication_version: 1,
  accounts: [row("#P1", "Alpha"), row("#P2", "Bravo")],
  sync: {
    cycle: "2026-11",
    cycle_source: "settings",
    enabled: true,
    status: "complete",
    warning: null,
    last_checked_at: "2026-11-01T12:00:00Z",
    last_success_at: "2026-11-01T12:00:00Z",
    updated_at: "2026-11-01T12:00:00Z",
  },
};
const status = (meets: number) => ({
  season_id: 1,
  cycle: "2026-11",
  archived: false,
  main_minimum: 3,
  pools: {
    main: [],
    lazy: [
      {
        tag: "#2YQ",
        name: "Lazy One",
        active: true,
        candidates: 2,
        meets_rule: meets,
        results_state: "captured",
        allowance_ready: true,
        draw_state: "none",
      },
    ],
  },
});
const raffle = (revision: number, flags: string[]) => ({
  revision,
  cycle: "2026-11",
  season_status: "draft",
  draws: [],
  accounts: [
    {
      ...row("#P1", "Alpha"),
      bonus_review: flags.length
        ? { flags, override_reason: "", revision, updated_at: "t" }
        : null,
    },
  ],
});
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
let statusReads: number;
const reportDirty = vi.fn();
const routes = () => api.mock.calls.map((call) => call[0] as string);
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
  statusReads = 0;
  reportDirty.mockReset();
  api.mockReset().mockImplementation(async (route: string, method?: string) => {
    if (route.endsWith("/bonus-status"))
      return status(++statusReads === 1 ? 1 : 2);
    if (route.endsWith("/account-review") && method === "PATCH")
      return raffle(2, ["lingering"]);
    if (route.endsWith("/bonus-raffle")) return raffle(1, []);
    return participation;
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function mount() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider
        value={{ owner: false, permissions: ["cwl_bonuses"] }}
      >
        <ParticipationWorkspace
          seasonId="1"
          seasons={[
            { id: 1, label: "November", status: "draft", signup_open: true },
          ]}
          onSeasonChange={() => {}}
          onBonus={() => {}}
          onDirty={reportDirty}
          urlState="pool=lazy"
          onUrlState={() => {}}
        />
      </DashboardPermissions.Provider>,
    ),
  );
}
const optionText = () =>
  host.querySelector<HTMLSelectElement>('select[name="clan"]')!.options[1]
    .textContent;
const named = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.trim() === name,
  )!;

it("the overview never reads bonus-raffle, even with the status loaded and no chips", async () => {
  await mount();
  expect(optionText()).toContain("1 of 2 meet");
  expect(routes().some((route) => route.includes("bonus-raffle"))).toBe(false);
  expect(
    host.querySelectorAll(".participation-list .roster-ui-chip"),
  ).toHaveLength(0);
});

it("saving infractions from Details rereads the status and updates the clan option", async () => {
  await mount();
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        'button[aria-label="Details for Alpha"]',
      )!
      .click(),
  );
  expect(
    routes().filter((route) => route.endsWith("/bonus-raffle")),
  ).toHaveLength(1);
  await act(async () =>
    host
      .querySelectorAll<HTMLInputElement>(
        '.participation-infractions input[type="checkbox"]',
      )[1]
      .click(),
  );
  // Back and page changes ask first: the workspace reports unsaved work.
  expect(reportDirty).toHaveBeenLastCalledWith(true);
  expect(statusReads).toBe(1);
  await act(async () => named("Save").click());
  expect(
    routes().filter((route) => route.endsWith("/account-review")),
  ).toHaveLength(1);
  expect(statusReads).toBe(2);
  expect(optionText()).toContain("2 of 2 meet");
});
