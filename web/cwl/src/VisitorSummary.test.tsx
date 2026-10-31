// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import VisitorSummary from "./VisitorSummary";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const counts = { total: 3, members: 2, staff: 1 };
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  api.mockReset(); api.mockResolvedValue({ today: "2026-11-01", timezone: "America/New_York", windows: { "1": counts, "7": counts, "30": counts }, series: [{ day: "2026-11-01", ...counts }] });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function mount(owner: boolean) {
  await act(async () => root.render(<DashboardPermissions.Provider value={{ owner, permissions: [] }}><VisitorSummary /></DashboardPermissions.Provider>));
}
it("does not fetch or render for nonowners", async () => {
  await mount(false); expect(api).not.toHaveBeenCalled(); expect(host.textContent).toBe("");
});
it("shows aggregate windows and an accessible daily alternative", async () => {
  await mount(true); expect(api).toHaveBeenCalledWith("/manage/visitors");
  expect(host.textContent).toContain("2 members · 1 staff");
  expect(host.querySelectorAll("dt")).toHaveLength(3);
  expect(host.querySelector('svg[role="img"]')?.getAttribute("aria-label")).toContain("30 days");
  expect(host.querySelector("summary")?.textContent).toBe("Daily counts");
});
it("ignores a late response after permission loss", async () => {
  let resolve!: (value: unknown) => void;
  api.mockReturnValue(new Promise((done) => { resolve = done; }));
  await mount(true); await mount(false);
  await act(async () => resolve({})); expect(host.textContent).toBe("");
});
it("shows an error and permits explicit retry", async () => {
  api.mockRejectedValueOnce(new Error("unavailable")); await mount(true);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("could not be loaded");
  await act(async () => host.querySelector("button")!.click());
  expect(api).toHaveBeenCalledTimes(2); expect(host.querySelector('[role="alert"]')).toBeNull();
});
it("uses singular member for a one-person count", async () => {
  const single = { total: 1, members: 1, staff: 0 };
  api.mockResolvedValue({ today: "2026-11-01", windows: { "1": single, "7": single, "30": single }, series: [] });
  await mount(true);
  expect(host.textContent).toContain("1 member · 0 staff");
  expect(host.textContent).not.toContain("1 members");
});
