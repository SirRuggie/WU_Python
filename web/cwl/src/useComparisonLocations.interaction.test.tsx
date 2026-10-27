// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createComparisonMemory } from "./comparisonMemory";
import { useComparisonLocations } from "./useComparisonLocations";
let host: HTMLDivElement, root: Root;
let memory = createComparisonMemory();
const fetcher = vi.fn();
function Probe({
  pool = "main",
  season = "1",
}: {
  pool?: string;
  season?: string;
}) {
  const result = useComparisonLocations(memory, season, pool, true, 1, 0);
  return (
    <>
      <output>{JSON.stringify(result.records)}</output>
      <p>{result.error}</p>
      <button onClick={result.refresh}>Refresh</button>
    </>
  );
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
  expect(host.querySelector("output")!.textContent).toBe(before);
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

it("hidden pending read applies records and freshness without starting another read", async () => {
  const response = fetcher.getMockImplementation()!;
  let finish!: () => void;
  fetcher.mockImplementation((url: string, options: RequestInit) =>
    url.includes("source=draft")
      ? new Promise((resolve) => {
          finish = async () => resolve(await response(url, options));
        })
      : response(url, options),
  );
  await mount();
  const previous = memory.pools.get("main")!.lastCheck;
  await act(async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
    finish();
  });
  expect(memory.records["#P"].current_clan_tag).toBe("#A");
  expect(memory.pools.get("main")!.lastCheck).not.toBe(previous);
  await act(async () => vi.advanceTimersByTimeAsync(300001));
  expect(
    fetcher.mock.calls.filter((call) =>
      String(call[0]).includes("source=draft"),
    ),
  ).toHaveLength(1);
});
it("published context remains immediately available when first switching pools", async () => {
  await mount();
  const published = memory.publication.published;
  const count = fetcher.mock.calls.filter((call) =>
    String(call[0]).includes("source=published"),
  ).length;
  await mount("lazy");
  expect(memory.publication.published).toBe(published);
  expect(
    fetcher.mock.calls.filter((call) =>
      String(call[0]).includes("source=published"),
    ),
  ).toHaveLength(count);
});

it("pending Refresh clicks produce exactly one refresh=1 request after settling", async () => {
  const response = fetcher.getMockImplementation()!;
  let finish!: () => void;
  let first = true;
  fetcher.mockImplementation((url: string, options: RequestInit) => {
    if (url.includes("source=draft") && first) {
      first = false;
      return new Promise((resolve) => {
        finish = async () => resolve(await response(url, options));
      });
    }
    return response(url, options);
  });
  await mount();
  await act(async () => {
    host.querySelector("button")!.click();
    host.querySelector("button")!.click();
  });
  expect(
    fetcher.mock.calls.filter((call) => String(call[0]).includes("refresh=1")),
  ).toHaveLength(0);
  await act(async () => finish());
  expect(
    fetcher.mock.calls.filter((call) => String(call[0]).includes("refresh=1")),
  ).toHaveLength(1);
});

it("pool, season and disposal abort their pending transport signals", async () => {
  fetcher.mockImplementation(() => new Promise(() => {}));
  await mount();
  let signals = fetcher.mock.calls.map((call) => call[1].signal as AbortSignal);
  await mount("lazy");
  expect(signals.every((signal) => signal.aborted)).toBe(true);
  signals = fetcher.mock.calls
    .slice(-2)
    .map((call) => call[1].signal as AbortSignal);
  await act(async () => root.render(<Probe pool="lazy" season="2" />));
  expect(signals.every((signal) => signal.aborted)).toBe(true);
  signals = fetcher.mock.calls
    .slice(-2)
    .map((call) => call[1].signal as AbortSignal);
  await leave();
  expect(signals.every((signal) => signal.aborted)).toBe(true);
});
it("timeout displays the last-results error without advancing freshness", async () => {
  fetcher.mockImplementation(
    (_url: string, options: RequestInit) =>
      new Promise((_, reject) =>
        options.signal!.addEventListener("abort", () =>
          reject(options.signal!.reason),
        ),
      ),
  );
  await mount();
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(host.textContent).toContain(
    "Couldn't update locations · showing last results",
  );
  expect(memory.pools.get("main")!.lastCheck).toBe(-Infinity);
});
