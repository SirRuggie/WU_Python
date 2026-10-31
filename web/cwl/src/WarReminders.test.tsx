// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WarReminders, { type ReminderEditor } from "./WarReminders";
import { api } from "./api";
vi.mock("./api", () => ({ api: vi.fn() }));
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
  vi.mocked(api).mockRejectedValueOnce(new Error("Settings changed. Reload."));
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
