// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./SeasonsPage", () => ({
  default: ({
    onDirty,
    onClans,
  }: {
    onDirty?: (value: boolean) => void;
    onClans?: () => void;
  }) => (
    <>
      <h1>Seasons fixture</h1>
      <button onClick={() => onDirty?.(true)}>Edit pool role</button>
      {onClans && <button onClick={onClans}>Next fixture Build</button>}
    </>
  ),
}));
vi.mock("./RosterWorkspace", () => ({
  default: () => (
    <p data-testid="roster-mode">
      {sessionStorage.getItem("wu-roster-1-mode")}
    </p>
  ),
}));
vi.mock("./ArrivalCheck", () => ({
  default: ({
    onFinalize,
    onResults,
  }: {
    onFinalize?: () => void;
    onResults?: () => void;
  }) => (
    <>
      <h1>Declaration fixture</h1>
      {onFinalize && <button onClick={onFinalize}>Finalize fixture</button>}
      {onResults && <button onClick={onResults}>Results fixture</button>}
    </>
  ),
}));
vi.mock("./ParticipationWorkspace", () => ({
  default: ({ onBonus }: { onBonus?: () => void }) => (
    <>
      <h1>Results fixture</h1>
      {onBonus && <button onClick={onBonus}>Bonus fixture</button>}
    </>
  ),
}));
vi.mock("./ReminderWorkspace", () => ({
  default: () => <p>Reminder fixture</p>,
}));
vi.mock("./PublicationWorkspace", () => ({
  default: () => <p>Publication fixture</p>,
}));
let cleanup: (() => Promise<void>) | undefined;
afterEach(async () => {
  await cleanup?.();
  cleanup = undefined;
  vi.restoreAllMocks();
  api.mockReset();
  sessionStorage.clear();
  localStorage.clear();
});
async function mount(path: string, permissions: string[]) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", path);
  sessionStorage.clear();
  localStorage.clear();
  sessionStorage.setItem("wu-roster-1-mode", JSON.stringify("compare"));
  api.mockImplementation(async (route: string) =>
    route === "/auth/me"
      ? {
          authenticated: true,
          user: { id: "123456789012345678", username: "Staff" },
          is_owner: false,
          can_edit: true,
          csrf_token: "fixture",
          dashboard_permissions: permissions,
        }
      : route === "/seasons"
        ? {
            seasons: [
              { id: 1, label: "November", status: "draft", signup_open: true },
            ],
            member_season: { season_id: 1, revision: 1 },
          }
        : route === "/config"
          ? { dev_fixture: true }
          : {},
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  cleanup = async () => {
    await act(async () => root.unmount());
    host.remove();
  };
  const settle = async () => {
    for (let i = 0; i < 5; i++)
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
  };
  await act(async () => root.render(<App />));
  await settle();
  const button = (label: string, selector = "button") =>
    [...host.querySelectorAll<HTMLButtonElement>(selector)].find(
      (node) => node.textContent?.trim() === label,
    );
  return { host, settle, button };
}
it("Declaration requires cwl_publish, not merely another publication step", async () => {
  const { button } = await mount("/cwl/readiness?season=1", [
    "cwl_roster",
    "cwl_send",
  ]);
  expect(button("Finalize fixture")).toBeUndefined();
});
it.each(["next", "sidebar"])(
  "dirty Seasons role edits guard %s navigation once",
  async (way) => {
    const { button, settle, host } = await mount("/cwl/settings?season=1", [
      "cwl_settings",
      "cwl_roster",
    ]);
    Object.defineProperty(window, "confirm", {
      configurable: true,
      writable: true,
      value: () => true,
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await act(async () => button("Edit pool role")!.click());
    await settle();
    const destination =
      way === "next"
        ? button("Next fixture Build")!
        : button("Build roster", ".sidebar button")!;
    await act(async () => destination.click());
    await settle();
    expect(confirm).toHaveBeenCalledOnce();
    expect(location.pathname).toBe("/cwl/settings");
    confirm.mockClear().mockReturnValue(true);
    await act(async () => destination.click());
    await settle();
    expect(confirm).toHaveBeenCalledOnce();
    expect(location.pathname).toBe("/cwl/roster");
    expect(host.querySelector('[data-testid="roster-mode"]')?.textContent).toBe(
      '"assign"',
    );
  },
);

it.each([
  ["/cwl/settings?season=1", ["cwl_settings"], "Next fixture Build", false],
  [
    "/cwl/settings?season=1",
    ["cwl_settings", "cwl_roster"],
    "Next fixture Build",
    true,
  ],
  ["/cwl/readiness?season=1", ["cwl_roster"], "Finalize fixture", false],
  [
    "/cwl/readiness?season=1",
    ["cwl_roster", "cwl_publish"],
    "Finalize fixture",
    true,
  ],
  ["/cwl/readiness?season=1", ["cwl_roster"], "Results fixture", false],
  [
    "/cwl/readiness?season=1",
    ["cwl_roster", "cwl_results"],
    "Results fixture",
    true,
  ],
  ["/cwl/results?season=1", ["cwl_results"], "Bonus fixture", false],
  [
    "/cwl/results?season=1",
    ["cwl_results", "cwl_bonuses"],
    "Bonus fixture",
    true,
  ],
  ["/cwl/results?season=1", ["cwl_results", "cwl_send"], "Bonus fixture", true],
  [
    "/cwl/reminders/signup?season=1",
    ["cwl_reminders"],
    "Next: Build roster ›",
    false,
  ],
  [
    "/cwl/reminders/signup?season=1",
    ["cwl_reminders", "cwl_roster"],
    "Next: Build roster ›",
    true,
  ],
] as const)(
  "destination grants govern %s %s %s",
  async (path, permissions, label, visible) => {
    const { button } = await mount(path, [...permissions]);
    expect(!!button(label)).toBe(visible);
  },
);
it("Reminders Next opens Accounts even when the last Build tab was Compare", async () => {
  const { button, settle, host } = await mount(
    "/cwl/reminders/signup?season=1",
    ["cwl_reminders", "cwl_roster"],
  );
  await act(async () => button("Next: Build roster ›")!.click());
  await settle();
  expect(location.pathname).toBe("/cwl/roster");
  expect(host.querySelector('[data-testid="roster-mode"]')?.textContent).toBe(
    '"assign"',
  );
});
