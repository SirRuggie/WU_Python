// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import AnnouncementFullTest from "./AnnouncementFullTest";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: (...args: unknown[]) =>
    args[0] === "/manage/announcement-test-channel"
      ? Promise.resolve({ channel_id: "", channel_name: "", revision: 0 })
      : api(...args),
}));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
async function mount(allowed = true) {
  await act(async () =>
    root.render(
      <AnnouncementFullTest
        seasonId="1"
        pool="lazy"
        version={2}
        generation="review-one"
        draft={{
          body: "Reviewed text",
          roster_url: "https://example.test/",
          channel_id: "123456789012345678",
        }}
        channels={[{ id: "123456789012345678", name: "test-room", type: 0 }]}
        allowed={allowed}
        clanNames={["Lazy.128", "Lazy.127"]}
      />,
    ),
  );
}
const button = (name: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === name,
  )!;
async function click(name: string) {
  await act(async () => button(name).click());
}
async function choose() {
  await act(async () => {
    const input = host.querySelector("input")!;
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "test");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    host.querySelector<HTMLElement>('[role="option"]')!.click(),
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockReset();
  api.mockResolvedValue({
    test: {
      request_id: "id",
      status: "complete",
      next_step: 4,
      steps: 4,
      error: null,
      channel_id: "123456789012345678",
    },
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("reviews the full ordered test and Cancel sends nothing", async () => {
  await mount();
  await choose();
  await click("Test full post");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Lazy.128, Lazy.127",
  );
  expect(document.querySelector("dialog")?.textContent).toContain("No pings");
  await click("Cancel");
  expect(api).not.toHaveBeenCalled();
});
it("queues only after confirmation and preserves identity on an ambiguous HTTP retry", async () => {
  await mount();
  await choose();
  api.mockRejectedValueOnce(new Error("Connection interrupted"));
  await click("Test full post");
  await click("Send full test");
  const first = api.mock.calls[0][2];
  expect(host.querySelector<HTMLInputElement>("input")!.disabled).toBe(true);
  expect(host.querySelector<HTMLInputElement>("input")!.value).toContain(
    "test-room",
  );
  await click("Test full post");
  expect(document.querySelector("dialog")?.textContent).toContain("#test-room");
  await click("Send full test");
  expect(api.mock.calls[1][2]).toEqual(first);
  expect(first).toMatchObject({
    version: 2,
    generation: "review-one",
    body: "Reviewed text",
  });
  expect(host.textContent).toContain("Full test complete");
});
it("permission loss closes a pending confirmation without sending", async () => {
  await mount();
  await choose();
  await click("Test full post");
  await mount(false);
  expect(document.querySelector("dialog")).toBeNull();
  expect(api).not.toHaveBeenCalled();
});
it("unlocks the test channel after a definite rejection", async () => {
  const { ApiError } = await import("./api");
  await mount();
  await choose();
  api.mockRejectedValueOnce(new ApiError("Forbidden", 403));
  await click("Test full post");
  await click("Send full test");
  expect(host.querySelector<HTMLInputElement>("input")!.disabled).toBe(false);
});
it("replaces confirmation with done, first-message link and one Close action", async () => {
  api.mockResolvedValue({
    test: {
      request_id: "id",
      status: "complete",
      next_step: 4,
      steps: 4,
      error: null,
      channel_id: "123456789012345678",
      message_url:
        "https://discord.com/channels/644963518025826315/123456789012345678/123456789012345679",
    },
  });
  await mount();
  await choose();
  await click("Test full post");
  await click("Send full test");
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain("Done");
  expect(dialog.textContent).toContain("2 clan images");
  expect(dialog.textContent).toContain("#test-room");
  expect(dialog.querySelectorAll("button")).toHaveLength(1);
  expect(dialog.querySelector("a")?.textContent).toBe("Open in Discord");
  expect(dialog.textContent).not.toContain("Send full test");
  await click("Close");
  expect(document.querySelector("dialog")).toBeNull();
  expect(host.textContent).toContain("Test posted to #test-room · no pings");
});
it("keeps live progress and a stopped result distinct from review", async () => {
  api.mockResolvedValue({
    test: {
      request_id: "id",
      status: "ready",
      next_step: 1,
      steps: 4,
      error: null,
      channel_id: "123456789012345678",
    },
  });
  await mount();
  await choose();
  await click("Test full post");
  await click("Send full test");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Posting 2 of 4 messages",
  );
  await click("Close");
});
it("shows uncertain delivery without offering an automatic retry", async () => {
  api.mockResolvedValue({
    test: {
      request_id: "id",
      status: "uncertain",
      next_step: 2,
      steps: 4,
      error: "Response lost",
      channel_id: "123456789012345678",
    },
  });
  await mount();
  await choose();
  await click("Test full post");
  await click("Send full test");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Stopped after 2 of 4 messages",
  );
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Response lost",
  );
  expect(api).toHaveBeenCalledTimes(1);
});
