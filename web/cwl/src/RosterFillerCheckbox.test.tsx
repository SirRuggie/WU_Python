// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { it, expect, vi, afterEach } from "vitest";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (orig) => ({
  ...(await orig<object>()),
  api: transport,
}));
import { ApiError } from "./api";
import RosterFillerCheckbox from "./RosterFillerCheckbox";
let root: ReturnType<typeof createRoot> | undefined;
let host: HTMLDivElement;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  transport.mockReset();
});
async function mount(onChanged = vi.fn()) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root!.render(
      <RosterFillerCheckbox
        seasonId="3"
        tag="#P2Y"
        name="Player"
        value={false}
        markRevision={4}
        revision={9}
        onChanged={onChanged}
      />,
    ),
  );
  return host.querySelector("input")!;
}
it("submits one explicit CAS mark on double tap and refreshes after confirmation", async () => {
  let finish!: (v: unknown) => void;
  transport.mockImplementation(
    () =>
      new Promise((r) => {
        finish = r;
      }),
  );
  const changed = vi.fn();
  const box = await mount(changed);
  await act(async () => {
    box.click();
    box.click();
  });
  expect(transport).toHaveBeenCalledTimes(1);
  expect(transport.mock.calls[0].slice(0, 3)).toEqual([
    "/seasons/3/roster-filler/%23P2Y",
    "PATCH",
    { revision: 9, roster_filler: true, mark_revision: 4 },
  ]);
  await act(async () => finish({ revision: 10 }));
  expect(changed).toHaveBeenCalledTimes(1);
});
it("shows stale-write failure without claiming saved or automatically retrying", async () => {
  transport.mockRejectedValue(new ApiError("Filler mark changed", 409));
  const changed = vi.fn();
  const box = await mount(changed);
  await act(async () => box.click());
  expect(host.textContent).toContain("Filler mark changed");
  expect(changed).not.toHaveBeenCalled();
  expect(transport).toHaveBeenCalledTimes(1);
  expect(box.checked).toBe(false);
});
it("disables further writes and refreshes protected parent state on permission loss", async () => {
  transport.mockRejectedValue(new ApiError("Access changed", 403));
  const changed = vi.fn();
  const box = await mount(changed);
  await act(async () => box.click());
  expect(box.disabled).toBe(true);
  expect(changed).toHaveBeenCalledTimes(1);
  expect(transport).toHaveBeenCalledTimes(1);
});
