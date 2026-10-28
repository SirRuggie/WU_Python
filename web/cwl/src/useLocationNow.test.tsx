// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import useLocationNow from "./useLocationNow";
import RosterAccountCard from "./RosterAccountCard";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
it("ticks account location ages at Compare's visible-page cadence and cleans up", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-28T12:00:00Z"));
  const visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("visible");
  function Harness() {
    const [now] = useLocationNow();
    return (
      <RosterAccountCard
        now={now}
        account={
          {
            tag: "#P",
            player_name: "Player",
            current_clan_name: "Home",
            current_clan_checked_at: "2026-10-28T12:00:00Z",
          } as never
        }
        assignedClanName="Not assigned"
        showPool={false}
        selected={false}
        selectionMode={false}
        disabled={false}
        canRoster
        canSignups
        archived={false}
        onToggle={() => {}}
        onDetails={() => {}}
        onAssign={() => {}}
        onSignup={() => {}}
      />
    );
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<Harness />));
    expect(host.textContent).toContain("Home · just now");
    await act(async () => vi.advanceTimersByTime(60_000));
    expect(host.textContent).toContain("Home · 1m ago");
    visibility.mockReturnValue("hidden");
    await act(async () => vi.advanceTimersByTime(60_000));
    expect(host.textContent).toContain("Home · 1m ago");
    visibility.mockReturnValue("visible");
    await act(async () => vi.advanceTimersByTime(30_000));
    expect(host.textContent).toContain("Home · 2m ago");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
  expect(vi.getTimerCount()).toBe(0);
});
