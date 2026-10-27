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
    await vi.advanceTimersByTimeAsync(98001);
    expect(check).toHaveBeenCalledTimes(calls + 1);
    run.dispose();
  });
  it("aborts an in-flight read on dispose and ignores its result", async () => {
    vi.useFakeTimers();
    let resolve!: (value: boolean) => void;
    const check = vi.fn(
      (_force: boolean, _signal: AbortSignal) =>
        new Promise<boolean>((r) => {
          resolve = r;
        }),
    );
    const busy = vi.fn();
    const run = createComparisonChecks(check, busy);
    run.setActive(true);
    const signal = check.mock.calls[0][1];
    run.dispose();
    expect(signal.aborted).toBe(true);
    resolve(true);
    await vi.advanceTimersByTimeAsync(90000);
    expect(check).toHaveBeenCalledTimes(1);
    expect(busy).toHaveBeenLastCalledWith(false);
    run.dispose();
  });
});

it("remount preserves the check deadline and performs one overdue non-forced read", async () => {
  vi.useFakeTimers();
  const check = vi.fn().mockResolvedValue(false);
  let last = -Infinity;
  const mount = () =>
    createComparisonChecks(check, vi.fn(), last, (time) => {
      last = time;
    });
  let run = mount();
  run.setActive(true);
  await vi.advanceTimersByTimeAsync(20_000);
  run.dispose();
  run = mount();
  run.setActive(true);
  expect(check).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(280_000);
  expect(check).toHaveBeenCalledTimes(2);
  run.dispose();
  await vi.advanceTimersByTimeAsync(300_001);
  run = mount();
  run.setActive(true);
  expect(check).toHaveBeenCalledTimes(3);
  expect(check.mock.calls.every((call) => call[0] === false)).toBe(true);
  run.dispose();
});

it("hidden pauses scheduling while an in-flight read completes and advances freshness", async () => {
  vi.useFakeTimers();
  let finish!: (value: boolean) => void;
  let signal!: AbortSignal;
  const check = vi.fn((_force, current: AbortSignal) => {
    signal = current;
    return new Promise<boolean>((resolve) => {
      finish = resolve;
    });
  });
  const complete = vi.fn();
  const run = createComparisonChecks(check, vi.fn(), -Infinity, complete);
  run.setActive(true);
  run.setActive(false);
  expect(signal.aborted).toBe(false);
  finish(true);
  await vi.advanceTimersByTimeAsync(0);
  expect(complete).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(300001);
  expect(check).toHaveBeenCalledTimes(1);
  run.setActive(true);
  expect(check).toHaveBeenCalledTimes(2);
  run.dispose();
});
it("queues exactly one forced refresh after a pending read settles", async () => {
  vi.useFakeTimers();
  let finish!: (value: boolean) => void;
  const check = vi.fn(
    (_force: boolean, _signal: AbortSignal) =>
      new Promise<boolean>((resolve) => {
        finish = resolve;
      }),
  );
  const run = createComparisonChecks(check, vi.fn());
  run.setActive(true);
  run.refresh();
  run.refresh();
  run.refresh();
  expect(check).toHaveBeenCalledTimes(1);
  finish(true);
  await vi.advanceTimersByTimeAsync(0);
  expect(check).toHaveBeenCalledTimes(2);
  expect(check.mock.calls[1][0]).toBe(true);
  finish(false);
  await vi.advanceTimersByTimeAsync(2000);
  expect(check).toHaveBeenCalledTimes(2);
  run.dispose();
});
it("times out a hung read after twenty seconds without consuming freshness", async () => {
  vi.useFakeTimers();
  let signal!: AbortSignal;
  const check = vi.fn((_force, current: AbortSignal) => {
    signal = current;
    return new Promise<boolean>(() => {});
  });
  const complete = vi.fn();
  const run = createComparisonChecks(check, vi.fn(), -Infinity, complete);
  run.setActive(true);
  await vi.advanceTimersByTimeAsync(19999);
  expect(signal.aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(signal.aborted).toBe(true);
  expect(signal.reason.name).toBe("TimeoutError");
  expect(complete).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(2000);
  expect(check).toHaveBeenCalledTimes(2);
  run.dispose();
});
it("retries failed empty first loads every two seconds for a bounded cycle", async () => {
  vi.useFakeTimers();
  const check = vi.fn().mockRejectedValue(new Error("offline"));
  const complete = vi.fn();
  const run = createComparisonChecks(check, vi.fn(), -Infinity, complete);
  run.setActive(true);
  await vi.advanceTimersByTimeAsync(89999);
  expect(check).toHaveBeenCalledTimes(45);
  expect(complete).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(298000);
  expect(check).toHaveBeenCalledTimes(45);
  await vi.advanceTimersByTimeAsync(1);
  expect(check).toHaveBeenCalledTimes(46);
  run.dispose();
});

it("retains one queued forced Refresh while hidden and clears checking", async () => {
  vi.useFakeTimers();
  let finish!: (value: boolean) => void;
  const check = vi.fn(
    (_force: boolean, _signal: AbortSignal) =>
      new Promise<boolean>((resolve) => {
        finish = resolve;
      }),
  );
  const busy = vi.fn();
  const run = createComparisonChecks(check, busy);
  run.setActive(true);
  run.refresh();
  run.setActive(false);
  expect(busy).toHaveBeenLastCalledWith(false);
  finish(false);
  await vi.advanceTimersByTimeAsync(1000);
  expect(check).toHaveBeenCalledTimes(1);
  run.setActive(true);
  expect(check).toHaveBeenCalledTimes(2);
  expect(check.mock.calls[1][0]).toBe(true);
  run.dispose();
});
