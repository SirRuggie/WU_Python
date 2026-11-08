// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ServerManagement from "./ServerManagement";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
const section = {
  id: "fwa_points",
  label: "Points",
  description: "Fictional settings",
  group: "War",
  endpoint: "/manage/points",
  allowed: true,
};
const other = {
  ...section,
  id: "fwa_bases",
  label: "Bases",
  endpoint: "/manage/bases",
};
const saved = {
  ...section,
  revision: 4,
  fields: [{ key: "message", label: "Message", type: "text", value: "Saved" }],
  actions: [
    {
      id: "reset",
      label: "Reset points",
      confirm: "Reset the selected points?",
    },
  ],
};
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const button = (name: string) =>
  [...document.querySelectorAll("button")].find(
    (node) =>
      node.textContent?.trim() === name ||
      node.textContent?.startsWith(name + "Fictional"),
  )!;
async function click(name: string) {
  await act(async () => button(name).click());
}
async function dirty() {
  const field = document.querySelector<HTMLInputElement>("#manage-message")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(field, "Unsaved");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  window.requestAnimationFrame = (callback) =>
    window.setTimeout(() => callback(0), 0);
  transport.mockReset().mockImplementation(async (url, method) => {
    if (method) return { message: "Done" };
    if (url === "/manage") return { sections: [section, other] };
    return saved;
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<ServerManagement area="fwa-settings" />));
  await click("Points");
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("Cancel, Escape and Back retain unsaved settings without another request", async () => {
  await dirty();
  const calls = transport.mock.calls.length;
  await click("← FWA tools");
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "You have changes that are not saved. Leave without saving?",
  );
  expect(document.activeElement?.textContent).toBe("Cancel");
  await click("Cancel");
  expect(
    document.querySelector<HTMLInputElement>("#manage-message")!.value,
  ).toBe("Unsaved");
  await click("← FWA tools");
  await act(async () =>
    document
      .querySelector(".confirm-dialog")!
      .dispatchEvent(new Event("cancel", { cancelable: true })),
  );
  await click("← FWA tools");
  await act(async () =>
    window.dispatchEvent(new PopStateEvent("popstate", { state: {} })),
  );
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(
    document.querySelector<HTMLInputElement>("#manage-message")!.value,
  ).toBe("Unsaved");
  expect(transport).toHaveBeenCalledTimes(calls);
});
it("an action sends exactly one original payload only after explicit confirmation", async () => {
  const calls = transport.mock.calls.length;
  await click("Reset points");
  expect(transport).toHaveBeenCalledTimes(calls);
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Reset the selected points?",
  );
  await click("Cancel");
  expect(transport).toHaveBeenCalledTimes(calls);
  await act(async () => {
    button("Reset points").click();
    button("Reset points").click();
  });
  const confirm = [
    ...document.querySelectorAll<HTMLButtonElement>(".confirm-dialog button"),
  ].find((node) => node.textContent === "Reset points")!;
  await act(async () => {
    confirm.click();
    confirm.click();
  });
  const writes = transport.mock.calls.filter((call) => call[1]);
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/manage/points/actions/reset");
  expect(writes[0][1]).toBe("POST");
  expect(writes[0][2]).toMatchObject({
    revision: 4,
    values: { message: "Saved" },
  });
});
it("closing the page cancels a pending action", async () => {
  await click("Reset points");
  await act(async () => root.render(<div>Another page</div>));
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(transport.mock.calls.filter((call) => call[1])).toHaveLength(0);
});
