// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WarReminders, { type ReminderEditor } from "./WarReminders";
import { api } from "./api";
vi.mock("./api", () => ({
  api: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));
const { ApiError } = await import("./api");
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
let editor: ReminderEditor | null;
const onEditor = (next: ReminderEditor | null) => {
  editor = next;
};
const onDirty = vi.fn();
const data = {
  settings: {
    enabled: false,
    channel_id: "",
    minutes: [60],
    war_started: false,
    audience: "remaining",
  },
  revision: "one",
  history: [],
};
async function render(active: boolean) {
  await act(async () =>
    root.render(
      <WarReminders
        tag="#TEST"
        channels={[]}
        embedded
        active={active}
        onDirty={onDirty}
        onEditor={onEditor}
      />,
    ),
  );
}
function edit() {
  act(() =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent?.trim() === "+ 12h")!
      .click(),
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  vi.mocked(api).mockReset().mockResolvedValue(data);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});
it("retains hidden drafts without polling", async () => {
  await render(true);
  edit();
  expect(editor?.changes).toBe(1);
  await render(false);
  const calls = vi.mocked(api).mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(45000);
  });
  expect(api).toHaveBeenCalledTimes(calls);
  expect(editor?.changes).toBe(1);
  await render(true);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(api).toHaveBeenCalledTimes(calls + 1);
  expect(editor?.changes).toBe(1);
  expect(host.textContent).not.toContain("Save reminders");
});
it("keeps conflicted drafts until explicitly discarded", async () => {
  await render(true);
  edit();
  vi.mocked(api).mockRejectedValueOnce(new Error("Settings changed. Refresh."));
  await act(async () => {
    expect(await editor!.save()).toBe(false);
  });
  expect(editor?.changes).toBe(1);
  expect(host.textContent).toContain("Settings changed");
  expect(api).toHaveBeenLastCalledWith(
    "/manage/clans/%23TEST/war-reminders",
    "PUT",
    { settings: { ...data.settings, minutes: [720, 60] }, revision: "one" },
  );
  act(() => editor!.discard());
  expect(editor?.changes).toBe(0);
});

const saved = {
  ...data,
  settings: { ...data.settings, channel_id: "123456789012345678" },
};
const switchInput = () =>
  host.querySelector<HTMLInputElement>('input[role="switch"]')!;
it("saves the switch at once from the saved settings and keeps unsaved edits", async () => {
  vi.mocked(api).mockResolvedValue(saved);
  await render(true);
  edit();
  expect(editor?.changes).toBe(1);
  vi.mocked(api).mockResolvedValueOnce({
    ...saved,
    settings: { ...saved.settings, enabled: true },
    revision: "two",
  });
  await act(async () => switchInput().click());
  expect(api).toHaveBeenLastCalledWith(
    "/manage/clans/%23TEST/war-reminders",
    "PUT",
    { settings: { ...saved.settings, enabled: true }, revision: "one" },
  );
  expect(switchInput().checked).toBe(true);
  // The unsaved 12h time stays; the switch is not an unsaved change.
  expect(editor?.changes).toBe(1);
  expect(host.textContent).toContain("12h before end");
  vi.mocked(api).mockResolvedValueOnce({
    ...saved,
    settings: { ...saved.settings, enabled: true, minutes: [720, 60] },
    revision: "three",
  });
  await act(async () => {
    expect(await editor!.save()).toBe(true);
  });
  expect(api).toHaveBeenLastCalledWith(
    "/manage/clans/%23TEST/war-reminders",
    "PUT",
    {
      settings: { ...saved.settings, enabled: true, minutes: [720, 60] },
      revision: "two",
    },
  );
  expect(editor?.changes).toBe(0);
});
it("does not count the switch as a change and rolls it back when saving fails", async () => {
  vi.mocked(api).mockResolvedValue(saved);
  await render(true);
  vi.mocked(api).mockRejectedValueOnce(new Error("Discord is unavailable."));
  await act(async () => switchInput().click());
  expect(switchInput().checked).toBe(false);
  expect(editor?.changes).toBe(0);
  expect(host.querySelector('[role="alert"]')!.textContent).toBe(
    "Discord is unavailable.",
  );
});
it("keeps the draft and shows the server message on a conflict", async () => {
  vi.mocked(api).mockResolvedValue(saved);
  await render(true);
  edit();
  vi.mocked(api).mockRejectedValueOnce(
    new ApiError("Reminders changed. Reload before saving.", 409),
  );
  await act(async () => switchInput().click());
  expect(switchInput().checked).toBe(false);
  expect(host.textContent).toContain(
    "Reminders changed. Reload before saving.",
  );
  expect(host.textContent).toContain("12h before end");
  expect(editor?.changes).toBe(1);
});
it("puts the status first and Test & history before Copy, with the history flagged when closed", async () => {
  vi.mocked(api).mockResolvedValue({
    ...saved,
    history: [
      {
        at: "2026-10-21T12:00:00Z",
        event: "60",
        test: false,
        status: "uncertain",
      },
    ],
  });
  await render(true);
  const text = host.textContent!;
  expect(text.indexOf("Reminder status")).toBeLessThan(
    text.indexOf("Test & history"),
  );
  expect(text.indexOf("Test & history")).toBeLessThan(
    text.indexOf("Copy reminder settings"),
  );
  expect(text).toContain("Test & history · 1 need review");
  expect(host.querySelectorAll("details > summary")[1]?.textContent).toContain(
    "Test & history",
  );
  const details = [...host.querySelectorAll("details")].find((d) =>
    d.querySelector("summary")?.textContent?.startsWith("Test & history"),
  )!;
  expect(details.open).toBe(false);
  expect(details.textContent).toContain("Delivery history");
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([path]) => String(path).endsWith("/preview")),
  ).toBe(false);
});
