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
  vi.useRealTimers();
});
it("bounds repeated visible events and rerenders to one read per30seconds", async () => {
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
