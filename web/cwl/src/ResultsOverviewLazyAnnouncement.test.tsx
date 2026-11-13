// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
const grants = vi.hoisted(() => ({ send: true }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: (name: string) => name !== "cwl_send" || grants.send,
}));
import ParticipationWorkspace from "./ParticipationWorkspace";

const status = {
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
        candidates: 8,
        meets_rule: 5,
        results_state: "captured",
        allowance_ready: true,
        draw_state: "none",
      },
      {
        tag: "#8QQ",
        name: "Lazy Two",
        active: true,
        candidates: 8,
        meets_rule: 5,
        results_state: "captured",
        allowance_ready: true,
        draw_state: "approved",
      },
    ],
  },
};
const participation = {
  publication_version: 1,
  accounts: [],
  sync: {
    cycle: "2026-11",
    cycle_source: "settings",
    enabled: true,
    status: "complete",
    warning: null,
    last_checked_at: null,
    last_success_at: null,
    updated_at: null,
  },
};
let host: HTMLDivElement;
let root: Root;

async function mount(state: string) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ParticipationWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
        onBonus={() => {}}
        urlState={state}
        onUrlState={() => {}}
      />,
    ),
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  grants.send = true;
  api
    .mockReset()
    .mockImplementation(async (route: string) =>
      route.endsWith("/bonus-status")
        ? status
        : route === "/announcement-roles"
          ? { roles: [] }
          : participation,
    );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("All clans on the Lazy tab shows Announcements with both rows", async () => {
  await mount("pool=lazy");
  const group = host.querySelector(".lazy-announce-group");
  expect(group?.querySelector("h3")?.textContent).toBe("Announcements");
  const rows = [...host.querySelectorAll(".lazy-announce-row")];
  expect(rows.map((row) => row.querySelector("p")?.textContent)).toEqual([
    "Bonus winners · 1 of 2 approved",
    "Infractions",
  ]);
  expect(rows.every((row) => !row.querySelector("button")?.disabled)).toBe(
    true,
  );
  // Nothing is fetched until a row is opened.
  expect(
    api.mock.calls.some((call) =>
      /lazy-(announcement|infractions)/.test(String(call[0])),
    ),
  ).toBe(false);
});

it("the Main tab shows no rows; staff without send access see only Infractions", async () => {
  await mount("pool=main");
  expect(host.querySelector(".lazy-announce-row")).toBeNull();
  await act(async () => root.unmount());
  host.remove();
  grants.send = false;
  await mount("pool=lazy");
  const rows = [...host.querySelectorAll(".lazy-announce-row")];
  expect(rows.map((row) => row.querySelector("p")?.textContent)).toEqual([
    "Infractions",
  ]);
  expect(
    host.querySelector('[aria-label="Open bonus announcement"]'),
  ).toBeNull();
});
