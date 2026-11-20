// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import DashboardSearch from "./DashboardSearch";
import type { Session } from "./api";
const mocks = vi.hoisted(() => ({ api: vi.fn(), accounts: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: mocks.api,
}));
vi.mock("./accountDisplay", async (original) => ({
  ...(await original<object>()),
  loadAccountDisplay: mocks.accounts,
}));
vi.mock("./TownHallIcon", () => ({ default: () => <span>TH</span> }));
let host: HTMLDivElement, root: Root;
const session = { user: { id: "fixture" }, csrf_token: "fixture" } as Session;
const props = {
  session,
  query: "fixture",
  onQuery: vi.fn(),
  kind: "all" as const,
  onKind: vi.fn(),
  page: 0,
  onPage: vi.fn(),
  onTasks: vi.fn(),
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mocks.api.mockReset();
  mocks.accounts.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});
it("loads the normal authorized family snapshot once, not per search query", async () => {
  mocks.accounts.mockResolvedValue({ accounts: [] });
  mocks.api.mockImplementation(async (path: string) =>
    path === "/approved-clans"
      ? { clans: [{ tag: "#R2Y", name: "Fixture family" }] }
      : { results: [] },
  );
  await act(async () =>
    root.render(<DashboardSearch {...props} includeFamily />),
  );
  await act(async () => vi.advanceTimersByTime(350));
  await act(async () =>
    root.render(<DashboardSearch {...props} query="another" includeFamily />),
  );
  await act(async () => vi.advanceTimersByTime(350));
  expect(mocks.accounts).toHaveBeenCalledTimes(1);
  expect(
    mocks.api.mock.calls.filter(([path]) => path === "/approved-clans"),
  ).toHaveLength(1);
});
it("lets public Clash rows arrive while family loads, without non-editor directory reads", async () => {
  let finish: (v: unknown) => void = () => {};
  mocks.accounts.mockImplementation(
    () => new Promise((resolve) => (finish = resolve)),
  );
  mocks.api.mockResolvedValue({
    results: [
      { kind: "clan", tag: "#C2Y", name: "Public fixture", source: "clash" },
    ],
  });
  await act(async () =>
    root.render(<DashboardSearch {...props} includeFamily={false} />),
  );
  await act(async () => vi.advanceTimersByTime(350));
  expect(host.textContent).toContain("Public fixture");
  expect(host.textContent).toContain("Loading your linked accounts");
  expect(
    mocks.api.mock.calls.some(([path]) => path === "/approved-clans"),
  ).toBe(false);
  await act(async () => finish({ accounts: [] }));
  expect(host.textContent).not.toContain("Loading your linked accounts");
});
