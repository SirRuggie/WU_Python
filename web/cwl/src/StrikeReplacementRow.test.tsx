// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api, ApiError } from "./api";
import StrikeReplacementRow from "./StrikeReplacementRow";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
let revision = 7;
const button = (text: string) =>
  [...document.body.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === text,
  )!;
const click = async (text: string) => act(async () => button(text).click());
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  revision = 7;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (!method || method === "GET")
      return { revision, priority: "high", note: "Saved", is_manual: true };
    throw new ApiError("Changed by someone else", 409);
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function render(canManage = true) {
  await act(async () =>
    root.render(
      <StrikeReplacementRow
        tag="#P2Y"
        canManage={canManage}
        onDirty={() => {}}
        onWorking={() => {}}
      />,
    ),
  );
}
it("retains the same draft after conflict and only retries using an explicit refreshed revision", async () => {
  await render();
  await click("Edit");
  const input = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(input, "My note");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("Save priority");
  expect(vi.mocked(api).mock.calls.at(-1)).toEqual([
    "/strikes/replacement-list/%23P2Y",
    "PUT",
    { revision: 7, priority: "high", note: "My note" },
  ]);
  expect(host.querySelector("textarea")).toBe(input);
  expect(input.value).toBe("My note");
  expect(button("Save priority").disabled).toBe(true);
  revision = 8;
  await click("Reload");
  expect(input.value).toBe("My note");
  await click("Save priority");
  expect(vi.mocked(api).mock.calls.at(-1)?.[2]).toMatchObject({
    revision: 8,
    note: "My note",
  });
});
it("clears with a confirmation and displayed revision, never a native confirm", async () => {
  const native = vi.fn();
  vi.stubGlobal("confirm", native);
  await render();
  await click("Edit");
  await click("Clear priority");
  expect(document.body.textContent).toContain("Strike history stays.");
  expect(
    vi.mocked(api).mock.calls.filter((c) => c[1] === "DELETE"),
  ).toHaveLength(0);
  await click("Clear");
  expect(vi.mocked(api).mock.calls.at(-1)).toEqual([
    "/strikes/replacement-list/%23P2Y",
    "DELETE",
    { revision: 7 },
  ]);
  expect(native).not.toHaveBeenCalled();
});
it("read-only staff have no editor or write controls", async () => {
  await render(false);
  expect(host.textContent).toContain("Replacement: High");
  expect(host.querySelector("button")).toBeNull();
  expect(vi.mocked(api).mock.calls).toHaveLength(1);
});

it("staff readers see the saved note without manager controls", async () => {
  await render(false);
  expect(host.textContent).toContain("Saved");
  expect(
    [...host.querySelectorAll("button")].some(
      (button) => button.textContent === "Edit",
    ),
  ).toBe(false);
});
