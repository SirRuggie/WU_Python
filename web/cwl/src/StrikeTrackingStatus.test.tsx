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
    expect(transport).toHaveBeenCalledTimes(5);
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
    expect(transport).toHaveBeenCalledTimes(5);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(transport).toHaveBeenCalledTimes(6);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(transport).toHaveBeenCalledTimes(6);
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
it("times out a hung check and permits an explicit Retry", async () => {
  vi.useFakeTimers();
  try {
    transport.mockImplementationOnce(() => new Promise(() => {}));
    await render(false);
    expect(host.textContent).toContain("Checking");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_001);
    });
    expect(host.textContent).toContain("timed out");
    const retry = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
      (b) => b.textContent === "Retry",
    )!;
    await act(async () => retry.click());
    expect(transport).toHaveBeenCalledTimes(2);
    expect(host.textContent).not.toContain("timed out");
  } finally {
    vi.useRealTimers();
  }
});
it("forces a post-retry read and ignores the older poll", async () => {
  vi.useFakeTimers();
  try {
    let old: ((value: unknown) => void) | undefined;
    await render(true);
    transport.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          old = resolve;
        }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    transport.mockResolvedValueOnce({}).mockResolvedValueOnce({
      clans: statusRows.map((r) => ({
        ...r,
        retry_pending: r.clan_tag === "#B",
      })),
    });
    const retry = [
      ...host.querySelectorAll<HTMLButtonElement>(
        ".strikes-tracking-clan button",
      ),
    ].find((b) => b.textContent === "Retry")!;
    await act(async () => retry.click());
    expect(host.textContent).toContain("Retry queued");
    await act(async () => old?.({ clans: statusRows }));
    expect(host.textContent).toContain("Retry queued");
    expect(transport).toHaveBeenCalledTimes(4);
  } finally {
    vi.useRealTimers();
  }
});

it("marks Queuing but not the completed Retry queued label", async () => {
  let finish!: (value: unknown) => void;
  transport.mockImplementation((path) =>
    path.endsWith("/retry")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve({ clans: statusRows }),
  );
  await render(true);
  const retry = host.querySelector<HTMLButtonElement>(
    ".strikes-tracking-clan:nth-child(2) button",
  )!;
  expect(retry.hasAttribute("aria-busy")).toBe(false);
  await act(async () => retry.click());
  expect(retry.textContent?.trim()).toBe("Queuing…");
  expect(retry.getAttribute("aria-busy")).toBe("true");
  expect(retry.disabled).toBe(true);
  await act(async () => retry.click());
  expect(
    transport.mock.calls.filter(([path]) => path.endsWith("/retry")),
  ).toHaveLength(1);
  await act(async () => finish({ queued: true }));
  transport.mockResolvedValue({
    clans: statusRows.map((row) =>
      row.clan_tag === "#B" ? { ...row, retry_pending: true } : row,
    ),
  });
  await act(async () => root.unmount());
  root = createRoot(host);
  await render(true);
  const queued = host.querySelector<HTMLButtonElement>(
    ".strikes-tracking-clan:nth-child(2) button",
  )!;
  expect(queued.textContent?.trim()).toBe("Retry queued");
  expect(queued.disabled).toBe(true);
  expect(queued.hasAttribute("aria-busy")).toBe(false);
});

async function renderCompact(rows: unknown[]) {
  transport.mockResolvedValue({ clans: rows });
  await act(async () =>
    root.render(<StrikeTrackingStatus canRetry={false} compact />),
  );
  await act(async () => {
    await Promise.resolve();
  });
  return host.querySelector("summary")!;
}

it("compact status is a link counting clans that need review, and only when there are some", async () => {
  const summary = await renderCompact(statusRows);
  expect(summary.textContent).toBe("3 clans need review ›");
  expect(summary.classList.contains("review")).toBe(true);
  expect(host.querySelector("summary span")).toBeNull();
});

it("compact status uses the singular and does not count healthy or idle clans", async () => {
  // "idle" is not in the TrackingStatus type yet; the count compares strings.
  const idle = { ...statusRows[0], clan_tag: "#I", status: "idle" };
  const summary = await renderCompact([statusRows[0], idle, statusRows[3]]);
  expect(summary.textContent).toBe("1 clan needs review ›");
});

it("compact status reads All clans on track as muted text when none need review", async () => {
  const idle = { ...statusRows[0], clan_tag: "#I", status: "idle" };
  const summary = await renderCompact([statusRows[0], idle]);
  expect(summary.textContent).toBe("All clans on track");
  expect(summary.classList.contains("review")).toBe(false);
  expect(host.textContent).not.toContain("need review");
});

it("compact status opens the same tracking details", async () => {
  const summary = await renderCompact(statusRows);
  expect(host.querySelector("details")!.open).toBe(false);
  await act(async () => summary.click());
  expect(host.querySelector("details")!.open).toBe(true);
  expect(host.textContent).toContain("Late Clan");
});

it("does not offer Retry for idle clans but keeps it for problem clans", async () => {
  const idle = {
    ...statusRows[0],
    clan_tag: "#I",
    clan_name: "Idle Clan",
    status: "idle",
  };
  transport.mockResolvedValue({ clans: [idle, ...statusRows.slice(1)] });
  await render(true);
  const clans = [...host.querySelectorAll(".strikes-tracking-clan")];
  const idleClan = clans.find((c) => c.textContent?.includes("Idle Clan"))!;
  expect(idleClan.querySelector("button")).toBeNull();
  expect(
    clans.filter((c) => c !== idleClan).every((c) => c.querySelector("button")),
  ).toBe(true);
});

it("shows slow clans as muted text inside the details, only when there are some", async () => {
  await render(false);
  expect(host.textContent).not.toContain("scanned late");
  await act(async () => root.unmount());
  root = createRoot(host);
  transport.mockResolvedValue({
    clans: [
      { ...statusRows[0], slow: true },
      { ...statusRows[0], clan_tag: "#S2", slow: true },
    ],
  });
  await render(false);
  expect(host.querySelector(".strikes-tracking-body")!.textContent).toContain(
    "2 clans scanned late",
  );
  await act(async () => root.unmount());
  root = createRoot(host);
  transport.mockResolvedValue({
    clans: [{ ...statusRows[0], slow: true }, statusRows[0]],
  });
  await render(false);
  expect(host.textContent).toContain("1 clan scanned late");
  expect(host.textContent).not.toContain("1 clans scanned late");
});
