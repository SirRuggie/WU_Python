// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import RefreshControl, {
  RefreshButton,
  useRefreshTime,
} from "./RefreshControl";
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("keeps icon-only Refresh name/tooltip and busy indication", async () => {
  await act(async () =>
    root.render(<RefreshControl updatedAt={0} busy onRefresh={() => {}} />),
  );
  const b = host.querySelector<HTMLButtonElement>('[aria-label="Refresh"]')!;
  expect(b.title).toBe("Refresh");
  expect(b.textContent).toBe("");
  expect(b.disabled).toBe(true);
  expect(b.getAttribute("aria-busy")).toBe("true");
  expect(b.querySelector(".is-refreshing")).not.toBeNull();
});
it("blocks immediate duplicate selects until the same read finishes", async () => {
  let done!: () => void;
  const read = vi.fn(
    () =>
      new Promise<void>((r) => {
        done = r;
      }),
  );
  await act(async () =>
    root.render(<RefreshButton busy={false} onRefresh={read} />),
  );
  const b = host.querySelector("button")!;
  await act(async () => {
    b.click();
    b.click();
  });
  expect(read).toHaveBeenCalledOnce();
  expect(b.disabled).toBe(true);
  await act(async () => done());
  expect(b.disabled).toBe(false);
});
it("announces busy-to-done only, never initial or later time ticks", async () => {
  const render = (busy: boolean, time: number) =>
    act(async () =>
      root.render(
        <RefreshControl updatedAt={time} busy={busy} onRefresh={() => {}} />,
      ),
    );
  await render(false, 1000);
  expect(host.querySelector('[role="status"]')).toBeNull();
  await render(true, 1000);
  expect(host.querySelector('[role="status"]')).toBeNull();
  await render(false, 2000);
  expect(host.querySelector('[role="status"]')).not.toBeNull();
  await render(false, 3000);
  expect(host.querySelector('[role="status"]')).toBeNull();
});
it("only offers explicit Pause/Resume names for automatic reads", async () => {
  const pause = vi.fn();
  await act(async () =>
    root.render(
      <RefreshControl
        updatedAt={0}
        busy={false}
        onRefresh={() => {}}
        onPauseChange={pause}
      />,
    ),
  );
  expect(host.querySelectorAll("button")).toHaveLength(1);
  await act(async () =>
    root.render(
      <RefreshControl
        updatedAt={0}
        busy={false}
        onRefresh={() => {}}
        intervalSeconds={30}
        onPauseChange={pause}
      />,
    ),
  );
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Pause automatic refresh"]',
      )!
      .click(),
  );
  expect(pause).toHaveBeenLastCalledWith(true);
  await act(async () =>
    root.render(
      <RefreshControl
        updatedAt={0}
        busy={false}
        onRefresh={() => {}}
        intervalSeconds={30}
        paused
        onPauseChange={pause}
      />,
    ),
  );
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Resume automatic refresh"]',
      )!
      .click(),
  );
  expect(pause).toHaveBeenLastCalledWith(false);
});
it("leaves same-error Try again as the only read action", async () => {
  await act(async () =>
    root.render(
      <RefreshControl
        updatedAt={0}
        busy={false}
        onRefresh={() => {}}
        intervalSeconds={30}
        onPauseChange={() => {}}
        showRefresh={false}
      />,
    ),
  );
  expect(host.querySelector('[aria-label="Refresh"]')).toBeNull();
  expect(
    host.querySelector('[aria-label="Pause automatic refresh"]'),
  ).not.toBeNull();
});
it("records successful read completion and retains it after a failure", async () => {
  function Sample({ busy, error = "" }: { busy: boolean; error?: string }) {
    const time = useRefreshTime(busy, true, error);
    return <output>{time ?? "unknown"}</output>;
  }
  const clock = vi.spyOn(Date, "now").mockReturnValue(1234);
  await act(async () => root.render(<Sample busy />));
  await act(async () => root.render(<Sample busy={false} />));
  expect(host.textContent).toBe("1234");
  clock.mockReturnValue(5678);
  await act(async () => root.render(<Sample busy />));
  await act(async () =>
    root.render(<Sample busy={false} error="Read failed" />),
  );
  expect(host.textContent).toBe("1234");
});
