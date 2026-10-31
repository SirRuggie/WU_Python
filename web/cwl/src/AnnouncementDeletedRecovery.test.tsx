// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import Recovery from "./AnnouncementDeletedRecovery";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const queued = vi.fn();
const props = {
  seasonId: "1",
  pool: "lazy" as const,
  cycle: "2026-11",
  version: 2,
  generation: "g1",
  channel: "123456789012345678",
  channelName: "lazy",
  roleNames: ["Lazy CWL"],
  clans: [{ tag: "#ABC", name: "Lazy.128", pages: 1, status: "not_started" }],
  preview: null,
  allowed: true,
  onQueued: queued,
};
async function mount(allowed = true) {
  await act(async () => root.render(<Recovery {...props} allowed={allowed} />));
}
async function click(text: string) {
  const button = [...document.querySelectorAll("button")]
    .filter((button) => button.textContent?.includes(text))
    .at(-1);
  expect(button).toBeTruthy();
  await act(async () => button!.click());
}
beforeEach(() => {
  api.mockReset();
  queued.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("checks read-only and requires explicit ping-again confirmation", async () => {
  api
    .mockResolvedValueOnce({ deleted: true, message_id: "987654321098765432" })
    .mockResolvedValue({});
  await mount();
  expect(api).toHaveBeenCalledTimes(1);
  expect(document.querySelector("dialog")).toBeNull();
  expect(host.textContent).toContain("Previous post was deleted");
  await click("Send again");
  expect(api).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).toContain("Earlier image posts stay");
  expect(document.body.textContent).toContain("Lazy.128");
  await click("Send again");
  expect(api.mock.calls[1]).toEqual([
    "/seasons/1/manage-bridge/lazy/send",
    "POST",
    {
      generation: "g1",
      channel_id: props.channel,
      version: 2,
      deleted_message_id: "987654321098765432",
      confirm_resend: true,
    },
  ]);
  expect(queued).toHaveBeenCalledOnce();
});
it("cancel or existing message never sends", async () => {
  api.mockResolvedValueOnce({
    deleted: true,
    message_id: "987654321098765432",
  });
  await mount();
  await click("Send again");
  await click("Cancel");
  expect(api).toHaveBeenCalledTimes(1);
  const now = Date.now();
  vi.spyOn(Date, "now").mockReturnValue(now + 31000);
  api.mockResolvedValueOnce({ deleted: false });
  await click("Check posted");
  expect(document.body.textContent).toContain("still exists");
  expect(api.mock.calls.every((call) => call.length === 1)).toBe(true);
});
it("ignores a late deleted response after permission loss", async () => {
  let resolve!: (value: unknown) => void;
  api.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  await mount();
  await click("Check posted");
  await mount(false);
  await act(async () =>
    resolve({ deleted: true, message_id: "987654321098765432" }),
  );
  expect(document.querySelector("dialog")).toBeNull();
  expect(api).toHaveBeenCalledTimes(1);
});
