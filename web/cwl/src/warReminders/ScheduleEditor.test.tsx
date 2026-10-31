// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ScheduleEditor from "./ScheduleEditor";
import type { ReminderSettings } from "./types";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const settings: ReminderSettings = {
  enabled: false,
  channel_id: "123456789012345678",
  minutes: [480, 60],
  war_started: false,
  audience: "remaining",
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});
it("hides configured quick-add times and keeps explicit add/remove edits", () => {
  const onChange = vi.fn();
  act(() =>
    root.render(
      <ScheduleEditor
        settings={settings}
        channels={[{ id: settings.channel_id, name: "war-room", type: 0 }]}
        disabled={false}
        onChange={onChange}
      />,
    ),
  );
  const buttons = () => [...host.querySelectorAll("button")];
  expect(buttons().some((b) => b.textContent?.trim() === "+ 8h")).toBe(false);
  expect(buttons().some((b) => b.textContent?.trim() === "+ 1h")).toBe(false);
  const add = buttons().find((b) => b.textContent?.trim() === "+ 12h")!;
  act(() => add.click());
  expect(onChange).toHaveBeenLastCalledWith({ minutes: [720, 480, 60] });
  act(() =>
    buttons()
      .find((b) => b.getAttribute("aria-label") === "Remove 8h reminder")!
      .click(),
  );
  expect(onChange).toHaveBeenLastCalledWith({ minutes: [60] });
  expect(host.textContent).toContain("Remind who?");
  expect(host.textContent).toContain("Players with attacks left");
  expect(host.querySelector<HTMLInputElement>('[role="combobox"]')!.value).toBe(
    "#war-room",
  );
  expect(host.textContent).not.toContain(settings.channel_id);
});
it("does not expose an unavailable destination ID or edit while disabled", () => {
  act(() =>
    root.render(
      <ScheduleEditor
        settings={settings}
        channels={[]}
        disabled
        onChange={vi.fn()}
      />,
    ),
  );
  expect(host.querySelector<HTMLInputElement>('[role="combobox"]')!.value).toBe(
    "Selected channel unavailable",
  );
  expect(host.querySelector("fieldset")!.disabled).toBe(true);
  expect(host.textContent).not.toContain(settings.channel_id);
});
