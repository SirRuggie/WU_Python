// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { summarizeArrivalReadiness } from "./arrivalReadiness";
import useDeclarationData from "./useDeclarationData";
let root: ReturnType<typeof createRoot>,
  host: HTMLDivElement,
  value: ReturnType<typeof useDeclarationData>;
const now = Date.parse("2026-10-28T12:00:00Z");
function Probe() {
  value = useDeclarationData("1");
  return null;
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(now);
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.includes("arrival-check")
              ? {
                  source: "published",
                  accounts: [
                    {
                      tag: "#P",
                      current_clan_tag: "#A",
                      current_clan_name: "Amber",
                      current_clan_checked_at: new Date(now).toISOString(),
                    },
                  ],
                }
              : { accounts: [], clans: [] },
          ),
        ),
    ),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it("reads published only, retains last records on failure, and never forces except Refresh", async () => {
  await act(async () => root.render(<Probe />));
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every((c) => !String(c[0]).includes("refresh=1")),
  ).toBe(true);
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
    "source=published",
  );
  await act(async () => vi.advanceTimersByTimeAsync(299999));
  expect(fetch).toHaveBeenCalledTimes(3);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(fetch).toHaveBeenCalledTimes(6);
  vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 400 }));
  await act(async () => value.refresh());
  expect(value.error).toBe("Couldn't update · showing last results");
  expect(value.records["#P"].current_clan_name).toBe("Amber");
  expect(
    vi.mocked(fetch).mock.calls.some((c) => String(c[0]).includes("refresh=1")),
  ).toBe(true);
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every((c) => !c[1]?.method || c[1]?.method === "GET"),
  ).toBe(true);
});

function arrivalReads() {
  return vi
    .mocked(fetch)
    .mock.calls.filter((c) => String(c[0]).includes("arrival-check"));
}
function pendingLocations() {
  let updating = true;
  let timestamp: string | undefined;
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (!String(url).includes("arrival-check")) return original(url, options);
    return new Response(
      JSON.stringify({
        source: "published",
        updating,
        accounts: [
          {
            tag: "#P",
            assigned_clan_tag: "#A",
            current_clan_tag: "#A",
            current_clan_name: "Amber",
            current_clan_checked_at: timestamp,
          },
        ],
      }),
    );
  });
  return {
    finish() {
      updating = false;
      timestamp = new Date(Date.now()).toISOString();
    },
    stale() {
      updating = true;
      timestamp = new Date(now - 600_000).toISOString();
    },
  };
}
it("follows an updating first load until actual locations arrive, with result-based Last checked", async () => {
  const pending = pendingLocations();
  await act(async () => root.render(<Probe />));
  expect(value.checkedAt).toBeUndefined();
  expect(value.records).toEqual({});
  pending.finish();
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(arrivalReads()).toHaveLength(2);
  expect(value.records["#P"].current_clan_name).toBe("Amber");
  expect(value.checkedAt).toBe(now);
  await act(async () => vi.advanceTimersByTimeAsync(6000));
  expect(arrivalReads()).toHaveLength(2);
});
function readiness() {
  return summarizeArrivalReadiness(
    Array.from({ length: 15 }, (_, i) => ({
      ...value.records["#P"],
      tag: String(i),
      assigned_clan_tag: "#A",
    })),
    { now: Date.now(), capacity: 15 },
  );
}
it("Refresh follows stale results until readiness becomes fresh", async () => {
  const pending = pendingLocations();
  pending.finish();
  await act(async () => root.render(<Probe />));
  await act(async () => vi.advanceTimersByTimeAsync(600_000));
  pending.stale();
  expect(readiness().refreshToConfirm).toBe(true);
  await act(async () => value.refresh());
  expect(value.checkedAt).toBe(now);
  pending.finish();
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(value.checkedAt).toBe(now + 600_000);
  expect(readiness().ready).toBe(true);
  expect(readiness().refreshToConfirm).toBe(false);
  expect(
    arrivalReads().filter((c) => String(c[0]).includes("refresh=1")),
  ).toHaveLength(1);
});
it("caps follow-ups at 60 seconds and never starts them from the five-minute check", async () => {
  pendingLocations();
  await act(async () => root.render(<Probe />));
  await act(async () => vi.advanceTimersByTimeAsync(60_000));
  const count = arrivalReads().length;
  expect(count).toBe(30);
  await act(async () => vi.advanceTimersByTimeAsync(298_000));
  expect(arrivalReads()).toHaveLength(count + 1);
  await act(async () => vi.advanceTimersByTimeAsync(10_000));
  expect(arrivalReads()).toHaveLength(count + 1);
});
it("pauses the follow-up window while hidden and aborts on unmount", async () => {
  pendingLocations();
  await act(async () => root.render(<Probe />));
  await act(async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(arrivalReads()).toHaveLength(1);
  await act(async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(arrivalReads()).toHaveLength(2);
});
it("reports first-load failure without claiming previous results", async () => {
  vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 400 }));
  await act(async () => root.render(<Probe />));
  expect(value.error).toBe("Couldn't check locations");
});
