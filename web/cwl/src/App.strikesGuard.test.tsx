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
vi.mock("./StrikesWorkspace", () => ({
  default: ({
    onDirty,
    onWorking,
  }: {
    onDirty: (dirty: boolean) => void;
    onWorking: (busy: boolean) => void;
  }) => {
    useEffect(() => {
      onDirty(true);
      return () => onDirty(false);
    }, [onDirty]);
    return (
      <>
        <input aria-label="Unsaved strike" defaultValue="750" />
        <button onClick={() => onWorking(true)}>Begin save</button>
        <button onClick={() => onWorking(false)}>Finish save</button>
      </>
    );
  },
}));
vi.mock("./ownerPrank/OwnerPrank", () => ({ default: () => null }));
vi.mock("./DashboardHome", () => ({ default: () => <p>Home reached</p> }));

afterEach(() => {
  state.api.mockReset();
  vi.restoreAllMocks();
  sessionStorage.clear();
  localStorage.clear();
});

it("keeps a strike draft guarded when Discard history replay receives no popstate", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({ wuDashboardIndex: 0 }, "", "/home");
  history.pushState({ wuDashboardIndex: 1 }, "", "/clans/strikes");
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
      host.querySelector('input[aria-label="Unsaved strike"]'),
    ).not.toBeNull();
    history.replaceState({ wuDashboardIndex: 0 }, "", "/home");
    await act(async () =>
      window.dispatchEvent(
        new PopStateEvent("popstate", { state: { wuDashboardIndex: 0 } }),
      ),
    );
    expect(go).toHaveBeenCalledWith(1);
    history.replaceState({ wuDashboardIndex: 1 }, "", "/clans/strikes");
    await act(async () =>
      window.dispatchEvent(
        new PopStateEvent("popstate", { state: { wuDashboardIndex: 1 } }),
      ),
    );
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "Discard your unsaved strike or replacement changes?",
    );
    await act(async () => button("Discard").click());
    expect(go).toHaveBeenCalledWith(-1);
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    expect(
      host.querySelector('input[aria-label="Unsaved strike"]'),
    ).not.toBeNull();
    await act(async () => button("Home").click());
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "Discard your unsaved strike or replacement changes?",
    );
    expect(host.textContent).not.toContain("Home reached");
    await act(async () => button("Begin save").click());
    await act(async () => button("Discard").click());
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "Wait for the save to finish.",
    );
    expect(
      host.querySelector('input[aria-label="Unsaved strike"]'),
    ).not.toBeNull();
    await act(async () => button("OK").click());
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    await act(async () => button("Finish save").click());
    await act(async () => button("Home").click());
    await act(async () => button("Discard").click());
    expect(host.textContent).toContain("Home reached");
    await act(async () => button("Strikes").click());
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    expect(nativeConfirm).not.toHaveBeenCalled();
    expect(
      state.api.mock.calls.every((call) => !call[1] || call[1] === "GET"),
    ).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

vi.mock("./ReplacementWorkspace", () => ({
  default: ({ initialClan }: { initialClan: string }) => (
    <p>Replacement clan {initialClan}</p>
  ),
}));
it("preserves the valid clan on a direct replacement route through auth canonicalization", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState(
    { wuDashboardIndex: 0 },
    "",
    "/clans/replacements?clan=%23Q2Y",
  );
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
      return { seasons: [], member_season: { season_id: null, revision: 0 } };
    if (path === "/config") return { dev_fixture: true };
    return {};
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<App />));
    for (let i = 0; i < 4; i++)
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
    expect(host.textContent).toContain("Replacement clan #Q2Y");
    expect(new URLSearchParams(location.search).get("clan")).toBe("#Q2Y");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
