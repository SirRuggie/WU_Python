// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { api, setCsrfToken, isExpectedCancel } from "./api";

// Each case moves the clock past the one-report-per-minute limit.
let clock = 1_000_000_000_000;
beforeEach(() => {
  clock += 120_000;
  vi.spyOn(Date, "now").mockReturnValue(clock);
  setCsrfToken("sample");
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setCsrfToken("");
});

function reportCalls(fetch: ReturnType<typeof vi.fn>) {
  return fetch.mock.calls.filter(
    (call) => String(call[0]) === "/api/cwl/issues/browser",
  );
}

describe("network issue reports", () => {
  it("reports a real connection failure on a visible page", async () => {
    const fetch = vi.fn((url: string) =>
      url === "/api/cwl/issues/browser"
        ? Promise.resolve(new Response('{"reference":"abc"}', { status: 200 }))
        : Promise.reject(new TypeError("Failed to fetch")),
    );
    vi.stubGlobal("fetch", fetch);
    await expect(api("/x", "POST", {})).rejects.toMatchObject({ status: 0 });
    expect(reportCalls(fetch)).toHaveLength(1);
    expect(reportCalls(fetch)[0][1].body).toBe('{"kind":"network_error"}');
  });
  it("does not report a request that the view cancelled", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetch = vi
      .fn()
      .mockRejectedValue(new DOMException("aborted", "AbortError"));
    vi.stubGlobal("fetch", fetch);
    await expect(
      api("/x", "GET", undefined, { signal: controller.signal }),
    ).rejects.toMatchObject({ status: 0 });
    expect(reportCalls(fetch)).toHaveLength(0);
  });
  it("does not report a view cancel with a custom abort reason", async () => {
    const controller = new AbortController();
    const timeout = new DOMException("Timed out", "TimeoutError");
    controller.abort(timeout);
    const fetch = vi.fn().mockRejectedValue(timeout);
    vi.stubGlobal("fetch", fetch);
    await expect(
      api("/x", "POST", {}, { signal: controller.signal }),
    ).rejects.toMatchObject({ status: 0 });
    expect(reportCalls(fetch)).toHaveLength(0);
  });
  it("does not report an AbortError without a signal", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValue(new DOMException("aborted", "AbortError"));
    vi.stubGlobal("fetch", fetch);
    await expect(api("/x", "POST", {})).rejects.toMatchObject({ status: 0 });
    expect(reportCalls(fetch)).toHaveLength(0);
  });
  it("does not report a failure while the page is hidden", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const fetch = vi.fn().mockRejectedValue(new TypeError("Load failed"));
    vi.stubGlobal("fetch", fetch);
    await expect(api("/x", "POST", {})).rejects.toMatchObject({ status: 0 });
    expect(reportCalls(fetch)).toHaveLength(0);
  });
  it("classifies only cancels and hidden pages as expected", () => {
    expect(isExpectedCancel(new TypeError("Failed to fetch"))).toBe(false);
    expect(isExpectedCancel(null)).toBe(false);
    expect(isExpectedCancel({ name: "AbortError" })).toBe(true);
  });
});
