// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeAll, beforeEach, afterEach, it, expect, vi } from "vitest";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./ReminderWorkspace", () => ({ default: () => null }));
vi.mock("./ArrivalCheck", () => ({ default: () => null }));
vi.mock("./rosterUi/Menu", async (original) => ({
  ...(await original<object>()),
  default: ({
    label,
    value,
    options,
    onValueChange,
    disabled,
    "aria-label": ariaLabel,
  }: {
    label: string;
    value: string;
    options: { value: string; label: string }[];
    onValueChange: (value: string) => void;
    disabled?: boolean;
    "aria-label"?: string;
  }) => (
    <select
      aria-label={ariaLabel || label}
      disabled={disabled}
      value={value}
      onChange={(e) => onValueChange(e.target.value)}
    >
      {options.map((row) => (
        <option key={row.value} value={row.value}>
          {row.label}
        </option>
      ))}
    </select>
  ),
}));
import App from "./App";
const seasons = [
  {
    id: 4,
    label: "2026-10",
    status: "archived",
    signup_open: false,
    history_only: 1,
  },
  {
    id: 3,
    label: "2026-09",
    status: "archived",
    signup_open: false,
    history_only: true,
  },
  {
    id: 2,
    label: "2026-08",
    status: "archived",
    signup_open: false,
    history_only: 1,
  },
  {
    id: 1,
    label: "November 2026",
    cwl_month: "2026-11",
    status: "draft",
    signup_open: true,
  },
];
// Load the actual lazy view modules before assertions; keep their components real.
beforeAll(async () => {
  await Promise.all([
    import("./RosterWorkspace"),
    import("./ResultsBonusesWorkspace"),
    import("./ParticipationWorkspace"),
  ]);
});
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  sessionStorage.clear();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  api.mockReset().mockImplementation(async (path: string) =>
    path === "/auth/me"
      ? {
          authenticated: true,
          user: { id: "123456789012345678", username: "Fixture" },
          is_owner: false,
          can_edit: true,
          csrf_token: "fixture",
          dashboard_permissions: ["cwl"],
        }
      : path === "/seasons"
        ? { seasons, member_season: { season_id: 1, revision: 1 } }
        : path === "/config"
          ? { dev_fixture: true }
          : path.endsWith("/publication")
            ? {
                draft_revision: 1,
                draft_changed: false,
                preview: {
                  accounts: [],
                  clans: [],
                  assigned_count: 0,
                  unassigned_count: 0,
                },
                published: null,
                last_publication: null,
                next_version: 1,
              }
            : /\/seasons\/[^/]+\/roster(?:\?|$)/.test(path)
              ? {
                  revision: 1,
                  accounts: [],
                  clans: [],
                  undo: null,
                  metadata_updating: false,
                }
              : path.endsWith("/participation")
                ? {
                    accounts: [],
                    publication_version: 1,
                    sync: {
                      cycle: "2026-11",
                      enabled: false,
                      status: "waiting",
                      warning: null,
                      last_checked_at: null,
                      last_success_at: null,
                      updated_at: null,
                    },
                  }
                : path.endsWith("/bonus-status")
                  ? {
                      season_id: 1,
                      cycle: "2026-11",
                      archived: false,
                      main_minimum: 3,
                      pools: { main: [], lazy: [] },
                    }
                  : path.startsWith("/staff-signup-members")
                    ? { options: [], next: null, truncated: false }
                    : path === "/family-clans"
                      ? { clans: [], status: "ok", source: "fixture" }
                      : path.startsWith("/linked-accounts")
                        ? { accounts: [], updating: false }
                        : path.endsWith("/signups")
                          ? { signups: [] }
                          : {},
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
const settle = async () => {
  for (let i = 0; i < 4; i++)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
};
it.each(["reminders", "declaration"])(
  "App %s picker preserves requested id and Back state with month labels",
  async (view) => {
    const path =
      view === "reminders" ? "/cwl/reminders/signup" : "/cwl/readiness";
    history.replaceState({ wuDashboardIndex: 1 }, "", `${path}?season=4`);
    await act(async () => root.render(<App />));
    await settle();
    const picker = host.querySelector<HTMLSelectElement>(
      'select[aria-label="Season"]',
    )!;
    expect(picker).not.toBeNull();
    expect(
      [...picker.options].filter((row) => row.value).map((row) => row.text),
    ).toEqual([
      "November 2026",
      "October 2026",
      "September 2026",
      "August 2026",
    ]);
    if (view === "reminders")
      expect(picker.options[0].text).toBe("Select a season");
    expect(picker.value).toBe("4");
    expect(location.search).toBe("?season=4");
    await act(async () => {
      picker.value = "3";
      picker.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await settle();
    expect(picker.value).toBe("3");
    await act(async () => {
      history.replaceState({ wuDashboardIndex: 0 }, "", `${path}?season=4`);
      window.dispatchEvent(
        new PopStateEvent("popstate", { state: { wuDashboardIndex: 0 } }),
      );
    });
    await settle();
    expect(picker.value).toBe("4");
    expect(location.search).toBe("?season=4");
    expect(
      api.mock.calls.every(
        (call) => call[1] === undefined || call[1] === "GET",
      ),
    ).toBe(true);
  },
);

const staffPicker = () =>
  host.querySelector<HTMLSelectElement>(
    'select[aria-label="Season"], .participation-season select, .roster-header-season select',
  )!;
const getOnly = () =>
  expect(
    api.mock.calls.every((call) => call[1] === undefined || call[1] === "GET"),
  ).toBe(true);
async function mountStaff(path: string) {
  history.replaceState({}, "", path);
  await act(async () => root.render(<App />));
  for (let attempt = 0; attempt < 60 && !staffPicker(); attempt++) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
  await settle();
}
it.each([
  {
    page: "reminders",
    path: "/cwl/reminders/signup",
    heading: ".cwl-page-header",
  },
  {
    page: "Results & bonuses",
    path: "/cwl/results",
    heading: ".participation-page-head",
  },
  { page: "Build roster", path: "/cwl/roster", heading: ".roster-header" },
])(
  "defaults the real App $page picker to November without a season query",
  async ({ path, heading }) => {
    await mountStaff(path);
    expect(
      host.querySelector(heading),
      host.textContent || "No App content",
    ).not.toBeNull();
    const picker = staffPicker();
    expect(picker).not.toBeNull();
    expect(picker.value).toBe("1");
    expect(picker.selectedOptions[0].textContent).toBe("November 2026");
    expect(new URLSearchParams(location.search).get("season")).toBe("1");
    getOnly();
  },
);
it("keeps a valid history-season URL and shows the notice before defaulting an unknown URL to November", async () => {
  await mountStaff("/cwl/results?season=4");
  expect(staffPicker().value).toBe("4");
  expect(staffPicker().selectedOptions[0].textContent).toBe("October 2026");
  await act(async () => root.unmount());
  root = createRoot(host);
  await mountStaff("/cwl/results?season=999");
  expect(staffPicker().value).toBe("1");
  expect(host.textContent).toContain(
    "The season in this link is not available",
  );
  getOnly();
});
it("keeps selected October on an actual season-list reload, then defaults November after a no-query reopen", async () => {
  await mountStaff("/cwl/reminders/signup");
  const picker = staffPicker();
  await act(async () => {
    picker.value = "4";
    picker.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
  expect(staffPicker().value).toBe("4");
  const reads = api.mock.calls.filter((call) => call[0] === "/seasons").length;
  await act(async () => window.dispatchEvent(new Event("focus")));
  await settle();
  expect(
    api.mock.calls.filter((call) => call[0] === "/seasons").length,
  ).toBeGreaterThan(reads);
  expect(staffPicker().value).toBe("4");
  expect(new URLSearchParams(location.search).get("season")).toBe("4");
  await act(async () => root.unmount());
  root = createRoot(host);
  await mountStaff("/cwl/reminders/signup");
  expect(staffPicker().value).toBe("1");
  expect(staffPicker().selectedOptions[0].textContent).toBe("November 2026");
  getOnly();
});
it("keeps member season1 instead of the higher-id history months", async () => {
  history.replaceState({}, "", "/signup");
  await act(async () => root.render(<App />));
  await settle();
  expect(host.querySelector(".member-season-line strong")?.textContent).toBe(
    "November 2026",
  );
  expect(location.pathname).toBe("/signup");
  expect(location.search).toBe("");
});
