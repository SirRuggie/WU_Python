// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardHome", () => ({ default: () => null }));
vi.mock("./TodoWorkspace", () => ({ default: () => null }));
import App from "./App";
afterEach(() => {
  vi.restoreAllMocks();
  api.mockReset();
});
it("App pool-change Cancel retains the draft; double confirmation clears it without writing", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/signup");
  localStorage.clear();
  sessionStorage.clear();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(
    () => {},
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  api.mockImplementation(async (path: string) =>
    path === "/auth/me"
      ? {
          authenticated: true,
          user: { id: "1", username: "Local fixture" },
          can_edit: false,
          is_owner: false,
          csrf_token: "fixture",
          dashboard_permissions: [],
        }
      : path === "/seasons"
        ? {
            seasons: [
              { id: 1, label: "November", status: "draft", signup_open: true },
            ],
            member_season: { season_id: 1, revision: 1 },
          }
        : path === "/config"
          ? { dev_fixture: true }
          : path.startsWith("/linked-accounts")
            ? {
                accounts: [
                  {
                    tag: "#PYY",
                    name: "Fixture",
                    town_hall: 18,
                    current_clan_type: "CWL",
                  },
                ],
                updating: false,
              }
            : path.endsWith("/signups")
              ? { signups: [] }
              : {},
  );
  const host = document.createElement("div"),
    root = createRoot(host);
  document.body.append(host);
  try {
    await act(async () => root.render(<App />));
    for (let i = 0; i < 4; i++)
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
    const main = [
      ...host.querySelectorAll<HTMLButtonElement>(".pool-choice-grid button"),
    ].find((b) => b.querySelector("strong")?.textContent === "Main CWL")!;
    await act(async () => main.click());
    const checkbox = host.querySelector<HTMLInputElement>(
      ".account-card input",
    )!;
    await act(async () => checkbox.click());
    expect(checkbox.checked).toBe(true);
    const lazy = [
      ...host.querySelectorAll<HTMLButtonElement>(".cwl-pool-tabs button"),
    ].find((b) => b.textContent === "Lazy CWL")!;
    const button = (name: string) =>
      [
        ...document.querySelectorAll<HTMLButtonElement>(
          ".confirm-dialog button",
        ),
      ].find((b) => b.textContent === name)!;
    await act(async () => lazy.click());
    expect(checkbox.checked).toBe(true);
    await act(async () => button("Cancel").click());
    expect(checkbox.checked).toBe(true);
    expect(lazy.getAttribute("aria-pressed")).toBe("false");
    await act(async () => {
      lazy.click();
      lazy.click();
    });
    await act(async () => {
      const confirm = button("Change CWL pool");
      confirm.click();
      confirm.click();
    });
    expect(lazy.getAttribute("aria-pressed")).toBe("true");
    expect(checkbox.checked).toBe(false);
    expect(
      api.mock.calls.filter((call) => call[1] && call[1] !== "GET"),
    ).toEqual([]);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
