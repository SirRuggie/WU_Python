// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import AnnouncementFullTest from "./AnnouncementFullTest";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
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
  await click("Test full post");
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
