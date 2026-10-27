import { afterEach, describe, expect, it, vi } from "vitest";
import { createComparisonChecks } from "./comparisonChecks";
afterEach(() => vi.useRealTimers());
describe("Compare check scheduler", () => {
  it("checks immediately and every five minutes, never forcing automatically", async () => {
    vi.useFakeTimers();
    const check = vi.fn().mockResolvedValue(false);
    const run = createComparisonChecks(check, vi.fn());
    run.setActive(true);
    await vi.advanceTimersByTimeAsync(299999);
    expect(check).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(check).toHaveBeenCalledTimes(2);
    expect(check.mock.calls.every((args) => args[0] === false)).toBe(true);
    run.refresh();
    await vi.advanceTimersByTimeAsync(0);
    expect(check.mock.calls.at(-1)?.[0]).toBe(true);
    run.dispose();
  });
  it("pauses while hidden or without clans and rechecks on overdue resume", async () => {
    vi.useFakeTimers();
    const check = vi.fn().mockResolvedValue(false);
    const run = createComparisonChecks(check, vi.fn());
    await vi.advanceTimersByTimeAsync(600000);
    expect(check).not.toHaveBeenCalled();
    run.setActive(true);
    await vi.advanceTimersByTimeAsync(0);
    run.setActive(false);
    await vi.advanceTimersByTimeAsync(600000);
    expect(check).toHaveBeenCalledTimes(1);
    run.setActive(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(check).toHaveBeenCalledTimes(2);
    run.dispose();
  });
  it("caps two-second followups at 90 seconds then waits for next cycle", async () => {
    vi.useFakeTimers();
    const check = vi.fn().mockResolvedValue(true);
    const run = createComparisonChecks(check, vi.fn());
    run.setActive(true);
    await vi.advanceTimersByTimeAsync(89999);
    const calls = check.mock.calls.length;
    expect(calls).toBe(45);
    await vi.advanceTimersByTimeAsync(200000);
    expect(check).toHaveBeenCalledTimes(calls);
    await vi.advanceTimersByTimeAsync(10001);
    expect(check).toHaveBeenCalledTimes(calls + 1);
    run.dispose();
  });
  it("aborts an in-flight read on deactivate and ignores its result", async () => {
    vi.useFakeTimers();
    let resolve!: (value: boolean) => void;
    const check = vi.fn(
      () =>
        new Promise<boolean>((r) => {
          resolve = r;
        }),
    );
    const busy = vi.fn();
    const run = createComparisonChecks(check, busy);
    run.setActive(true);
    run.setActive(false);
    resolve(true);
    await vi.advanceTimersByTimeAsync(90000);
    expect(check).toHaveBeenCalledTimes(1);
    expect(busy).toHaveBeenLastCalledWith(false);
    run.dispose();
  });
});
