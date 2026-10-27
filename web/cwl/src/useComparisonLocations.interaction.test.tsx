// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createComparisonMemory } from "./comparisonMemory";
import { useComparisonLocations } from "./useComparisonLocations";
let host: HTMLDivElement, root: Root;
let memory = createComparisonMemory();
const fetcher = vi.fn();
function Probe({ pool = "main" }: { pool?: string }) {
  const result = useComparisonLocations(memory, "1", pool, true, 1, 0);
  return <output>{JSON.stringify(result.records)}</output>;
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-27T12:00:00Z"));
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  memory = createComparisonMemory();
  fetcher.mockImplementation(async (url: string) => ({
    ok: true,
    json: async () => ({
      source: url.includes("source=published") ? "published" : "draft",
      updating: false,
      accounts: [
        {
          tag: "#P",
          current_clan_tag: "#A",
          current_clan_name: "A",
          current_clan_checked_at: new Date().toISOString(),
          current_clan_status: "current",
        },
      ],
    }),
  }));
  vi.stubGlobal("fetch", fetcher);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  fetcher.mockReset();
});
async function mount(pool = "main") {
  await act(async () => root.render(<Probe pool={pool} />));
}
async function leave() {
  await act(async () => root.render(null));
}
it("keeps identical records immediately on remount within five minutes without reads", async () => {
  await mount();
  expect(fetcher).toHaveBeenCalledTimes(2);
  const before = host.textContent;
  await leave();
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  await mount();
  expect(host.textContent).toBe(before);
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it("keeps records on overdue remount while starting one non-forced draft check", async () => {
  await mount();
  const before = JSON.stringify(memory.records);
  await leave();
  await act(async () => vi.advanceTimersByTimeAsync(300_001));
  fetcher.mockImplementation(() => new Promise(() => {}));
  await mount();
  expect(host.textContent).toBe(before);
  const urls = fetcher.mock.calls.map((call) => String(call[0]));
  expect(urls.filter((url) => url.includes("source=draft"))).toHaveLength(2);
  expect(urls.every((url) => !url.includes("refresh=1"))).toBe(true);
});
it("preserves records across pools, retaining each pool's deadline", async () => {
  await mount();
  const before = host.textContent;
  await mount("lazy");
  expect(host.textContent).toBe(before);
  const calls = fetcher.mock.calls.length;
  await mount("main");
  expect(host.textContent).toBe(before);
  expect(fetcher).toHaveBeenCalledTimes(calls);
});
it("an aborted initial read does not suppress the next mount's first result", async () => {
  fetcher.mockImplementation(() => new Promise(() => {}));
  await mount();
  await leave();
  await mount();
  expect(
    fetcher.mock.calls.filter((call) =>
      String(call[0]).includes("source=draft"),
    ),
  ).toHaveLength(2);
});
