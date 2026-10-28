import { afterEach, expect, it, vi } from "vitest";
import { createComparisonChecks } from "./comparisonChecks";
afterEach(() => vi.useRealTimers());
it("Declaration uses the shared runner without two-second polling, and only Refresh forces", async () => {
  vi.useFakeTimers();
  const read = vi.fn(async (_force: boolean, _signal: AbortSignal) => true);
  const runner = createComparisonChecks(
    read,
    () => {},
    -Infinity,
    () => {},
    false,
  );
  runner.setActive(true);
  await vi.advanceTimersByTimeAsync(0);
  expect(read.mock.calls[0]?.[0]).toBe(false);
  await vi.advanceTimersByTimeAsync(299999);
  expect(read).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(read).toHaveBeenCalledTimes(2);
  runner.refresh();
  await vi.advanceTimersByTimeAsync(0);
  expect(read.mock.calls.at(-1)?.[0]).toBe(true);
  runner.dispose();
});
