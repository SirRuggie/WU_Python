// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

const state = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: state.api,
}));
vi.mock("./RosterWorkspace", () => ({
  default: ({
    onDirty,
    onDirtySummary,
    onBusy,
  }: {
    onDirty: (dirty: boolean) => void;
    onDirtySummary: (summary: {
      weightCount: number;
      onlyWeights: boolean;
    }) => void;
    onBusy: (busy: boolean) => void;
  }) => {
    useEffect(() => {
      onDirty(true);
      onDirtySummary({ weightCount: 1, onlyWeights: true });
      return () => onDirty(false);
    }, [onDirty, onDirtySummary]);
    return (
      <>
        <input aria-label="Unsaved weight" defaultValue="750" />
        <button onClick={() => onBusy(true)}>Begin save</button>
        <button onClick={() => onBusy(false)}>Finish save</button>
      </>
    );
  },
}));
vi.mock("./DashboardHome", () => ({ default: () => <p>Home reached</p> }));

afterEach(() => {
  state.api.mockReset();
  vi.restoreAllMocks();
  sessionStorage.clear();
  localStorage.clear();
});

it("keeps a roster draft guarded when Discard history replay receives no popstate", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({ wuDashboardIndex: 0 }, "", "/home");
  history.pushState({ wuDashboardIndex: 1 }, "", "/cwl/roster?season=1");
  state.api.mockImplementation(async (path: string) => {
    if (path === "/auth/me")
      return {
        authenticated: true,
        user: { id: "1", username: "Staff" },
        is_owner: true,
        can_edit: true,
        csrf_token: "fixture",
      };
    if (path === "/seasons")
      return {
        seasons: [
          { id: 1, label: "November", status: "draft", signup_open: true },
        ],
        member_season: { season_id: 1, revision: 0 },
      };
    if (path === "/config") return { dev_fixture: true };
    return {};
  });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const nativeConfirm = vi.fn(() => false);
  window.confirm = nativeConfirm;
  const go = vi.spyOn(history, "go").mockImplementation(() => {});
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const settle = async () => {
    for (let i = 0; i < 4; i++)
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
  };
  const button = (name: string) =>
    [...document.querySelectorAll<HTMLButtonElement>("button")].find(
      (item) => item.textContent?.trim() === name,
    )!;
  try {
    await act(async () => root.render(<App />));
    await settle();
    expect(
      host.querySelector('input[aria-label="Unsaved weight"]'),
    ).not.toBeNull();
    history.replaceState({ wuDashboardIndex: 0 }, "", "/home");
    await act(async () =>
      window.dispatchEvent(
        new PopStateEvent("popstate", { state: { wuDashboardIndex: 0 } }),
      ),
    );
    expect(go).toHaveBeenCalledWith(1);
    history.replaceState({ wuDashboardIndex: 1 }, "", "/cwl/roster?season=1");
    await act(async () =>
      window.dispatchEvent(
        new PopStateEvent("popstate", { state: { wuDashboardIndex: 1 } }),
      ),
    );
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "You have 1 unsaved weight.",
    );
    await act(async () => button("Discard").click());
    expect(go).toHaveBeenCalledWith(-1);
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    expect(
      host.querySelector('input[aria-label="Unsaved weight"]'),
    ).not.toBeNull();
    await act(async () => button("Home").click());
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "You have 1 unsaved weight.",
    );
    expect(host.textContent).not.toContain("Home reached");
    await act(async () => button("Begin save").click());
    await act(async () => button("Discard").click());
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "Wait for the save to finish.",
    );
    expect(
      host.querySelector('input[aria-label="Unsaved weight"]'),
    ).not.toBeNull();
    await act(async () => button("OK").click());
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    await act(async () => button("Finish save").click());
    await act(async () => button("Home").click());
    await act(async () => button("Discard").click());
    expect(host.textContent).toContain("Home reached");
    await act(async () => button("Build roster").click());
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    expect(nativeConfirm).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
