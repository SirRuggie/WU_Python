// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./ReminderWorkspace", () => ({ default: () => null }));
vi.mock("./ArrivalCheck", () => ({ default: () => null }));
vi.mock("./rosterUi/Menu", () => ({
  default: ({
    label,
    value,
    options,
    onValueChange,
  }: {
    label: string;
    value: string;
    options: { value: string; label: string }[];
    onValueChange: (value: string) => void;
  }) => (
    <select
      aria-label={label}
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
  { id: 4, label: "2026-10", status: "archived", signup_open: false },
  { id: 3, label: "2026-09", status: "archived", signup_open: false },
  { id: 2, label: "2026-08", status: "archived", signup_open: false },
  {
    id: 1,
    label: "November 2026",
    cwl_month: "2026-11",
    status: "draft",
    signup_open: true,
  },
];
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

it("keeps the existing API staff default even when a different month displays first", async () => {
  history.replaceState({}, "", "/cwl/reminders/signup");
  await act(async () => root.render(<App />));
  await settle();
  const picker = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Season"]',
  )!;
  expect(picker.options[1].value).toBe("1");
  expect(picker.value).toBe("4");
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
