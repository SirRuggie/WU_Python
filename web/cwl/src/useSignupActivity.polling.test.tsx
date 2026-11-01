// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
vi.mock("./api", () => ({ api: vi.fn() }));
import { api } from "./api";
import useSignupActivity from "./useSignupActivity";
let root: Root, host: HTMLDivElement;
function Fixture({ render }: { render: number }) {
  useSignupActivity("1");
  return <span>{render}</span>;
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  vi.mocked(api).mockReset().mockResolvedValue({ items: [] });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("throttles visibility bursts while regular interval reads continue", async () => {
  await act(async () => root.render(<Fixture render={0} />));
  for (let n = 1; n <= 30; n++)
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      root.render(<Fixture render={n} />);
      await vi.advanceTimersByTimeAsync(500);
    });
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(15000));
  expect(api).toHaveBeenCalledTimes(2);
  await act(async () => vi.advanceTimersByTimeAsync(30000));
  expect(api).toHaveBeenCalledTimes(3);
});

it("does not skip interval ticks that fire just under thirty seconds", async () => {
  let tick!: () => void;
  vi.spyOn(window, "setInterval").mockImplementation((handler, delay) => {
    expect(delay).toBe(30000);
    tick = handler as () => void;
    return 123 as unknown as ReturnType<typeof window.setInterval>;
  });
  await act(async () => root.render(<Fixture render={0} />));
  for (let count = 1; count <= 3; count++) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(29980);
      tick();
    });
    expect(api).toHaveBeenCalledTimes(count + 1);
    await act(async () =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    expect(api).toHaveBeenCalledTimes(count + 1);
  }
});
