// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { visibleRefresh } from "./visibleRefresh";
let hidden = false;
let dispose = () => {};
beforeEach(() => {
  vi.useFakeTimers();
  hidden = false;
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
});
afterEach(() => {
  dispose();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("keeps the existing visible cadence and performs no initial duplicate read", async () => {
  const read = vi.fn();
  dispose = visibleRefresh(read, 30000);
  await vi.advanceTimersByTimeAsync(29999);
  expect(read).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(33);
  expect(read).toHaveBeenCalledTimes(1);
});
it("removes periodic work while hidden and catches up once on return", async () => {
  const read = vi.fn();
  dispose = visibleRefresh(read, 3000);
  hidden = true;
  document.dispatchEvent(new Event("visibilitychange"));
  expect(vi.getTimerCount()).toBe(0);
  await vi.advanceTimersByTimeAsync(30000);
  expect(read).not.toHaveBeenCalled();
  hidden = false;
  document.dispatchEvent(new Event("visibilitychange"));
  window.dispatchEvent(new Event("focus"));
  await vi.advanceTimersByTimeAsync(32);
  expect(read).toHaveBeenCalledTimes(1);
});
it("coalesces focus, visibility and an interval due in the same burst", async () => {
  const read = vi.fn();
  dispose = visibleRefresh(read, 3000);
  await vi.advanceTimersByTimeAsync(2990);
  window.dispatchEvent(new Event("focus"));
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(42);
  expect(read).toHaveBeenCalledTimes(1);
});
it("does not overlap a pending read and resumes after completion", async () => {
  let resolve!: () => void;
  const read = vi.fn(
    () =>
      new Promise<void>((done) => {
        resolve = done;
      }),
  );
  dispose = visibleRefresh(read, 3000);
  await vi.advanceTimersByTimeAsync(3032);
  expect(read).toHaveBeenCalledTimes(1);
  window.dispatchEvent(new Event("focus"));
  await vi.advanceTimersByTimeAsync(6000);
  expect(read).toHaveBeenCalledTimes(1);
  resolve();
  await Promise.resolve();
  await vi.advanceTimersByTimeAsync(3032);
  expect(read).toHaveBeenCalledTimes(2);
});
it("cleans pending catch-up and listeners on scope disposal", async () => {
  const read = vi.fn();
  dispose = visibleRefresh(read, 3000);
  window.dispatchEvent(new Event("focus"));
  dispose();
  window.dispatchEvent(new Event("focus"));
  await vi.advanceTimersByTimeAsync(6000);
  expect(read).not.toHaveBeenCalled();
});
it("does not start a timer when created hidden", async () => {
  hidden = true;
  const read = vi.fn();
  dispose = visibleRefresh(read, 1000);
  expect(vi.getTimerCount()).toBe(0);
  await vi.advanceTimersByTimeAsync(5000);
  expect(read).not.toHaveBeenCalled();
});
it("drops a queued burst if the tab hides before it runs", async () => {
  const read = vi.fn();
  dispose = visibleRefresh(read, 3000);
  window.dispatchEvent(new Event("focus"));
  hidden = true;
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(5000);
  expect(read).not.toHaveBeenCalled();
});
it("releases its in-flight guard after an owner-handled failed read", async () => {
  const read = vi
    .fn()
    .mockRejectedValueOnce(new Error("checked by page"))
    .mockResolvedValue(undefined);
  dispose = visibleRefresh(read, 3000);
  await vi.advanceTimersByTimeAsync(3032);
  expect(read).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(3000);
  expect(read).toHaveBeenCalledTimes(2);
});
