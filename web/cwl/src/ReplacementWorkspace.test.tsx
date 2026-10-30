// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api, ApiError } from "./api";
import ReplacementWorkspace from "./ReplacementWorkspace";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const row = {
  player_tag: "#P2Y",
  player_name: "Sample",
  clan_tag: "#R2Y",
  clan_name: "Family",
  active_strikes: 4,
  revision: 7,
  priority: "high",
  note: "Original",
  is_manual: true,
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue({
    candidates: [row],
    clans: [{ tag: "#R2Y", name: "Family" }],
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const button = (text: string) =>
  [...document.body.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
async function render() {
  await act(async () =>
    root.render(<ReplacementWorkspace permissions={[]} isOwner />),
  );
}
async function click(text: string) {
  expect(button(text)).toBeDefined();
  await act(async () => button(text).click());
}
async function input(node: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
it("retains a conflicting edit and only changes its baseline after explicit Reload", async () => {
  await render();
  await click("Edit");
  const note = [...host.querySelectorAll("input")].find(
    (n) => n.value === "Original",
  )!;
  expect(note).toBeDefined();
  await input(note, "Keep my text");
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method) throw new ApiError("Changed by someone else · Reload", 409);
    return { revision: 8 } as never;
  });
  await click("Save");
  expect(note.isConnected).toBe(true);
  expect(note.value).toBe("Keep my text");
  expect(host.textContent).toContain("Changed by someone else");
  expect(api).toHaveBeenCalledWith("/strikes/replacement-list/%23P2Y", "PUT", {
    priority: "high",
    note: "Keep my text",
    revision: 7,
  });
  await click("Reload list");
  expect(note.value).toBe("Keep my text");
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method ? ({} as never) : ({ candidates: [row], clans: [] } as never),
  );
  await click("Save");
  expect(api).toHaveBeenCalledWith("/strikes/replacement-list/%23P2Y", "PUT", {
    priority: "high",
    note: "Keep my text",
    revision: 8,
  });
});
it("clears with its displayed revision through an in-app confirmation", async () => {
  const confirm = vi.fn();
  vi.stubGlobal("confirm", confirm);
  await render();
  await click("Edit");
  await click("Clear priority");
  expect(host.textContent).toContain("Strike history stays.");
  expect(confirm).not.toHaveBeenCalled();
  await click("Clear");
  expect(api).toHaveBeenCalledWith(
    "/strikes/replacement-list/%23P2Y",
    "DELETE",
    { revision: 7 },
  );
  vi.unstubAllGlobals();
});
