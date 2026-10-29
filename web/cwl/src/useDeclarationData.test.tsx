// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
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
