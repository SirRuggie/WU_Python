// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import StrikeReviewResolution from "./StrikeReviewResolution";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api, ApiError } from "./api";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const button = (name: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent === name,
  )!;
const click = async (name: string) => act(async () => button(name).click());
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function input(value: string) {
  await act(async () => {
    const node = host.querySelector("textarea")!;
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function render(canManage = true) {
  const done = vi.fn();
  await act(async () =>
    root.render(
      <StrikeReviewResolution
        warKey="war-key"
        revision={3}
        reason="Missing final"
        canManage={canManage}
        onDirty={vi.fn()}
        onWorking={vi.fn()}
        onResolved={done}
      />,
    ),
  );
  return done;
}
it("requires an explicit confirmation, reason and displayed revision", async () => {
  const done = await render();
  await click("Resolve review");
  expect(button("Resolve and release hold").disabled).toBe(true);
  await input("Reviewed old final");
  await click("Resolve and release hold");
  expect(vi.mocked(api)).not.toHaveBeenCalled();
  await click("Resolve review");
  expect(vi.mocked(api)).toHaveBeenCalledWith(
    "/strikes/tracking/resolve",
    "POST",
    { war_key: "war-key", revision: 3, reason: "Reviewed old final" },
  );
  expect(done).toHaveBeenCalledOnce();
});
it("keeps a conflicting reason and uses a new revision only after explicit refresh", async () => {
  const done = await render();
  await click("Resolve review");
  await input("Keep this reason");
  vi.mocked(api).mockRejectedValueOnce(
    new ApiError("Changed by another staff member", 409),
  );
  await click("Resolve and release hold");
  await click("Resolve review");
  expect(host.querySelector("textarea")?.value).toBe("Keep this reason");
  expect(done).not.toHaveBeenCalled();
  vi.mocked(api).mockResolvedValueOnce({
    manual_review_required: true,
    review_revision: 4,
  });
  await click("Refresh review");
  await click("Resolve and release hold");
  await click("Resolve review");
  expect(vi.mocked(api).mock.calls.at(-1)).toEqual([
    "/strikes/tracking/resolve",
    "POST",
    { war_key: "war-key", revision: 4, reason: "Keep this reason" },
  ]);
});
it("shows the held review to read-only staff without mutation controls", async () => {
  await render(false);
  expect(host.textContent).toContain("Missing final");
  expect(host.querySelector("button")).toBeNull();
  expect(vi.mocked(api)).not.toHaveBeenCalled();
});
