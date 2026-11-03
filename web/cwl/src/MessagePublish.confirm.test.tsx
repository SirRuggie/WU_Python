// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
import MessagePublish from "./MessagePublish";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const page = {
  revision: "revision-1",
  posting_channel: "Local destination",
  target_url: null,
  destination_editor: null,
  actions: [
    {
      id: "post",
      label: "Post saved message",
      endpoint: "/api/cwl/fixture/publish",
    },
  ],
};
const writes = () => api.mock.calls.filter((call) => call[1] === "POST");
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === name,
  )!;
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  api
    .mockReset()
    .mockImplementation(async (_path: string, method?: string) =>
      method === "POST" ? { message: "Local queued" } : page,
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <MessagePublish
        endpoint="/api/cwl/fixture"
        dirty={false}
        busy={false}
        onBusy={() => {}}
      />,
    ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("posting Cancel is zero writes and double confirmation preserves one request identity", async () => {
  await act(async () => button("Post saved message", host).click());
  expect(writes()).toHaveLength(0);
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Local destination",
  );
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(writes()).toHaveLength(0);
  await act(async () => {
    button("Post saved message", host).click();
    button("Post saved message", host).click();
  });
  await act(async () => {
    const confirm = button(
      "Post saved message",
      document.querySelector(".confirm-dialog")!,
    );
    confirm.click();
    confirm.click();
  });
  expect(writes()).toHaveLength(1);
  expect(writes()[0][0]).toBe("/fixture/publish");
  expect(writes()[0][2]).toEqual({
    revision: "revision-1",
    request_id: expect.any(String),
  });
});
it("unmount before confirmation does not publish", async () => {
  await act(async () => button("Post saved message", host).click());
  await act(async () => root.render(<p>Closed</p>));
  expect(writes()).toHaveLength(0);
});
it("an endpoint change cancels a pending decision even with the same document revision", async () => {
  await act(async () => button("Post saved message", host).click());
  await act(async () =>
    root.render(
      <MessagePublish
        endpoint="/api/cwl/other-fixture"
        dirty={false}
        busy={false}
        onBusy={() => {}}
      />,
    ),
  );
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(writes()).toHaveLength(0);
});
it("closing after accepted publishing does not replay the request", async () => {
  let finish!: (value: object) => void;
  api.mockImplementation(async (_path: string, method?: string) =>
    method === "POST"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : page,
  );
  await act(async () => button("Post saved message", host).click());
  await act(async () =>
    button(
      "Post saved message",
      document.querySelector(".confirm-dialog")!,
    ).click(),
  );
  expect(writes()).toHaveLength(1);
  await act(async () => root.render(<p>Closed</p>));
  await act(async () => finish({ message: "Local completed" }));
  expect(writes()).toHaveLength(1);
  expect(host.textContent).toBe("Closed");
});
