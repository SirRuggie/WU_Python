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
vi.mock("./worldClocks/WorldClocksWorkspace", () => ({
  default: ({ onDirty }: { onDirty: (dirty: boolean) => void }) => {
    useEffect(() => {
      onDirty(true);
      return () => onDirty(false);
    }, [onDirty]);
    return <input aria-label="Unsaved clock" defaultValue="EST" />;
  },
}));
vi.mock("./DashboardHome", () => ({ default: () => <p>Home reached</p> }));

afterEach(() => {
  state.api.mockReset();
  vi.restoreAllMocks();
  sessionStorage.clear();
  localStorage.clear();
});

it("asks in the app's own dialog, never a browser pop-up, before leaving unsaved settings", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({ wuDashboardIndex: 0 }, "", "/settings/world-clocks");
  state.api.mockImplementation(async (path: string) => {
    if (path === "/prank/state") throw new Error("Not enabled in this fixture");
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
      host.querySelector('input[aria-label="Unsaved clock"]'),
    ).not.toBeNull();
    await act(async () => button("Home").click());
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "Leave without saving your changes?",
    );
    await act(async () => button("Cancel").click());
    await settle();
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    expect(
      host.querySelector('input[aria-label="Unsaved clock"]'),
    ).not.toBeNull();
    expect(host.textContent).not.toContain("Home reached");
    await act(async () => button("Home").click());
    await act(async () => button("Discard and continue").click());
    await settle();
    expect(host.textContent).toContain("Home reached");
    expect(nativeConfirm).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
