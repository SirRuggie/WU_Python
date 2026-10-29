import { afterEach, expect, it, vi } from "vitest";
import { createComparisonChecks } from "./comparisonChecks";
afterEach(() => vi.useRealTimers());
it("Declaration restarts one bounded loop for a new Refresh, and cancels on dispose", async () => {
  vi.useFakeTimers();
  const read = vi.fn(async (_force: boolean, _signal: AbortSignal) => true);
  const runner = createComparisonChecks(
    read,
    () => {},
    -Infinity,
    () => {},
    "declaration",
  );
  runner.setActive(true);
  await vi.advanceTimersByTimeAsync(50_000);
  expect(read).toHaveBeenCalledTimes(26);
  runner.refresh();
  await vi.advanceTimersByTimeAsync(12_000);
  expect(read).toHaveBeenCalledTimes(33);
  expect(read.mock.calls.filter(([force]) => force)).toHaveLength(1);
  runner.dispose();
  await vi.advanceTimersByTimeAsync(300_000);
  expect(read).toHaveBeenCalledTimes(33);
});
