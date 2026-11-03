// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./SavedSignups", () => ({
  default: ({ onWithdraw, signups }: any) => (
    <button onClick={() => onWithdraw(signups)}>
      Withdraw fixture accounts
    </button>
  ),
}));
vi.mock("./DashboardHome", () => ({ default: () => null }));
vi.mock("./MemberAssignments", () => ({ default: () => null }));
vi.mock("./TodoWorkspace", () => ({ default: () => null }));
import App from "./App";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const rows = [
  {
    tag: "#PYY",
    user_id: "1",
    player_name: "Fixture",
    pool: "main",
    prefer_crystal_1_or_lower: false,
    has_staff_placement: true,
  },
];
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === name,
  )!;
const writes = () =>
  api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/my-signups");
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
  api.mockReset().mockImplementation(async (path: string, method?: string) =>
    method === "DELETE"
      ? {}
      : path === "/auth/me"
        ? {
            authenticated: true,
            user: { id: "1", username: "Local fixture" },
            is_owner: false,
            can_edit: false,
            csrf_token: "fixture",
            dashboard_permissions: [],
          }
        : path === "/seasons"
          ? {
              seasons: [
                {
                  id: 1,
                  label: "November",
                  status: "draft",
                  signup_open: true,
                },
              ],
              member_season: { season_id: 1, revision: 1 },
            }
          : path === "/config"
            ? { dev_fixture: true }
            : path.startsWith("/linked-accounts")
              ? {
                  accounts: [{ tag: "#PYY", name: "Fixture", town_hall: 18 }],
                  updating: false,
                }
              : path.endsWith("/signups")
                ? { signups: rows }
                : path.endsWith("/my-assignments")
                  ? { published: null, accounts: [] }
                  : {},
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<App />));
  for (let i = 0; i < 4; i++)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  expect(button("Withdraw fixture accounts")).toBeTruthy();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("withdraw Cancel writes zero and double confirmation deletes each requested account once", async () => {
  await act(async () => button("Withdraw fixture accounts").click());
  expect(writes()).toHaveLength(0);
  expect(
    button(
      "Withdraw accounts",
      document.querySelector(".confirm-dialog")!,
    ).classList.contains("confirm-danger"),
  ).toBe(true);
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Clan assignments will be cleared for: Fixture.",
  );
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(writes()).toHaveLength(0);
  await act(async () => {
    button("Withdraw fixture accounts").click();
    button("Withdraw fixture accounts").click();
  });
  await act(async () => {
    const confirm = button(
      "Withdraw accounts",
      document.querySelector(".confirm-dialog")!,
    );
    confirm.click();
    confirm.click();
  });
  expect(writes()).toHaveLength(1);
  expect(writes()[0][1]).toBe("DELETE");
});
