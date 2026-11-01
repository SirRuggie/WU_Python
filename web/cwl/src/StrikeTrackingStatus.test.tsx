// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import StrikeTrackingStatus from "./StrikeTrackingStatus";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));

let host: HTMLDivElement;
let root: Root;
const statusRows = [
  {
    clan_tag: "#A",
    clan_name: "Current Clan",
    status: "healthy",
    current_war_state: "notInWar",
    latest_recorded_war_at: null,
  },
  {
    clan_tag: "#B",
    clan_name: "Late Clan",
    status: "behind",
    current_war_state: "warEnded",
    latest_recorded_war_at: "2026-10-19T12:00:00Z",
    error: "Final war check missing",
  },
  {
    clan_tag: "#C",
    clan_name: "Private Clan",
    status: "private",
    current_war_state: "private",
    latest_recorded_war_at: null,
  },
  {
    clan_tag: "#D",
    clan_name: "Failed Clan",
    status: "error",
    current_war_state: "unknown",
    latest_recorded_war_at: null,
    error: "Official API unavailable",
  },
];

async function render(canRetry: boolean) {
  await act(async () =>
    root.render(<StrikeTrackingStatus canRetry={canRetry} />),
  );
  await act(async () => {
    await Promise.resolve();
  });
  await act(async () => {
    host.querySelector("summary")!.click();
  });
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  transport.mockReset();
  transport.mockResolvedValue({ clans: statusRows });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shows honest counts, war state, last record and sanitized error text", async () => {
  await render(false);
  expect(host.textContent).toContain(
    "1 on track · 1 behind · 1 private · 1 error",
  );
  expect(host.textContent).toContain("Last war recorded");
  expect(host.textContent).toContain("Not yet");
  expect(host.textContent).toContain("War ended");
  expect(host.textContent).toContain("War log private");
  expect(host.textContent).toContain("Official API unavailable");
  expect(host.querySelectorAll(".strikes-tracking-clan button")).toHaveLength(
    0,
  );
});

it("only enables retry for nonhealthy clans with permission", async () => {
  await render(true);
  expect(host.querySelectorAll(".strikes-tracking-clan button")).toHaveLength(
    3,
  );
  const retry = host.querySelector<HTMLButtonElement>(
    ".strikes-tracking-clan:nth-child(2) button",
  )!;
  await act(async () => retry.click());
  expect(transport).toHaveBeenCalledWith("/strikes/tracking/retry", "POST", {
    clan_tag: "#B",
  });
});

it("clears protected rows when staff access is revoked", async () => {
  vi.useFakeTimers();
  try {
    await render(false);
    transport.mockRejectedValue(new ApiError("No access", 403));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(host.textContent).toContain("Status unavailable");
    expect(host.textContent).not.toContain("Private Clan");
  } finally {
    vi.useRealTimers();
  }
});

it("clears protected rows when retry permission is revoked", async () => {
  await render(true);
  transport.mockRejectedValue(new ApiError("No access", 403));
  const retry = host.querySelector<HTMLButtonElement>(
    ".strikes-tracking-clan:nth-child(2) button",
  )!;
  await act(async () => retry.click());
  expect(host.textContent).toContain("No access");
  expect(host.textContent).not.toContain("Private Clan");
});

it("bounds focus bursts, hidden polling and overlapping tracking reads", async () => {
  vi.useFakeTimers();
  let finish: ((value: unknown) => void) | undefined;
  try {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    await render(false);
    expect(transport).toHaveBeenCalledTimes(1);
    await act(async () => {
      for (let i = 0; i < 10; i++) window.dispatchEvent(new Event("focus"));
      await vi.advanceTimersByTimeAsync(29_999);
    });
    expect(transport).toHaveBeenCalledTimes(1);
    transport.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(transport).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(90_000);
    });
    expect(transport).toHaveBeenCalledTimes(2);
    await act(async () => {
      finish?.({ clans: statusRows });
    });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(90_000);
    });
    expect(transport).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(transport).toHaveBeenCalledTimes(3);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(transport).toHaveBeenCalledTimes(3);
  } finally {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    vi.useRealTimers();
  }
});

it("retains the initial in-flight read across StrictMode effect replay", async () => {
  let finish: ((value: unknown) => void) | undefined;
  transport.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await act(async () =>
    root.render(
      <StrictMode>
        <StrikeTrackingStatus canRetry={false} />
      </StrictMode>,
    ),
  );
  expect(transport).toHaveBeenCalledTimes(1);
  await act(async () => {
    finish?.({ clans: statusRows });
  });
  expect(host.textContent).toContain("1 on track");
  expect(host.textContent).not.toContain("Checking…");
});

it("does not suppress a scheduled tick that arrives just before thirty seconds", async () => {
  vi.useFakeTimers();
  let tick: (() => void) | undefined;
  const original = window.setInterval;
  const spy = vi.spyOn(window, "setInterval").mockImplementation(((
    callback: () => void,
    delay?: number,
  ) => {
    if (delay === 30_000) tick = callback;
    return original(callback, delay);
  }) as typeof window.setInterval);
  try {
    await render(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(29_999);
      tick?.();
    });
    expect(transport).toHaveBeenCalledTimes(2);
  } finally {
    spy.mockRestore();
    vi.useRealTimers();
  }
});
