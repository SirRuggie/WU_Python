// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import TestPanel from "./TestPanel";
import type { ReminderSettings } from "./types";
vi.mock("../api", () => ({ api: vi.fn() }));
vi.mock("../DiscordPreview", () => ({ DiscordText: () => null }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const settings: ReminderSettings = {
  enabled: false,
  channel_id: "123456789012345678",
  minutes: [60],
  war_started: false,
  audience: "remaining",
};
const delivered = vi.fn().mockResolvedValue(undefined);
function render(overrides: Partial<Parameters<typeof TestPanel>[0]> = {}) {
  act(() =>
    root.render(
      <TestPanel
        base="/manage/clans/%23P2Y/war-reminders"
        channelName="war-room"
        settings={settings}
        disabled={false}
        active={false}
        onDelivered={delivered}
        {...overrides}
      />,
    ),
  );
}
function button(text: string) {
  return [...document.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
}
async function click(text: string) {
  await act(async () => button(text).click());
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.open = true;
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.open = false;
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api)
    .mockReset()
    .mockResolvedValue({ urls: ["https://discord.com/channels/1/2/3"] });
  delivered.mockClear();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("requires a named channel confirmation and cancel performs no send", async () => {
  render();
  await click("Send test to selected channel");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Post a test reminder to #war-room?",
  );
  expect(api).not.toHaveBeenCalled();
  await click("Cancel");
  expect(api).not.toHaveBeenCalled();
  await click("Send test to selected channel");
  await click("Post test");
  expect(api).toHaveBeenCalledTimes(1);
  expect(api).toHaveBeenCalledWith(
    "/manage/clans/%23P2Y/war-reminders/test",
    "POST",
    expect.objectContaining({
      request_id: expect.any(String),
      settings: expect.objectContaining({
        channel_id: settings.channel_id,
        enabled: false,
      }),
    }),
  );
  expect(delivered).toHaveBeenCalledTimes(1);
});
it("refuses to send a changed destination from an old confirmation", async () => {
  render();
  await click("Send test to selected channel");
  render({
    settings: { ...settings, channel_id: "987654321098765432" },
    channelName: "different",
  });
  await click("Post test");
  expect(api).not.toHaveBeenCalled();
  expect(document.querySelector("dialog")).toBeNull();
});
it("preserves the receipt identity after uncertain delivery and never retries automatically", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Delivery unconfirmed"));
  render();
  await click("Send test to selected channel");
  await click("Post test");
  expect(api).toHaveBeenCalledTimes(1);
  const id = vi.mocked(api).mock.calls[0][2] as { request_id: string };
  await click("Send test to selected channel");
  expect(api).toHaveBeenCalledTimes(1);
  await click("Post test");
  expect(api).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api).mock.calls[1][2]).toMatchObject({
    request_id: id.request_id,
  });
});
it("does not offer a test when the selected channel cannot be named", () => {
  render({ channelName: "" });
  expect(button("Send test to selected channel").disabled).toBe(true);
});
