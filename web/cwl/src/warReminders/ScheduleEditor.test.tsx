// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ScheduleEditor from "./ScheduleEditor";
import type { ReminderSettings } from "./types";
import { pickerValue } from "../searchPickerTestUtils";
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
  expect(host.textContent).toContain("Who to remind");
  expect(host.textContent).not.toContain("Remind who?");
  expect(host.textContent).toContain("Players with attacks left");
  expect(pickerValue(host)).toBe("#war-room");
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
  expect(pickerValue(host)).toBe("Selected channel unavailable");
  expect(host.querySelector("fieldset")!.disabled).toBe(true);
  expect(host.textContent).not.toContain(settings.channel_id);
});
it("uses a fixed Reminders switch that saves through onToggle, not onChange", () => {
  const onChange = vi.fn(),
    onToggle = vi.fn();
  act(() =>
    root.render(
      <ScheduleEditor
        settings={settings}
        channels={[{ id: settings.channel_id, name: "war-room", type: 0 }]}
        disabled={false}
        onChange={onChange}
        onToggle={onToggle}
      />,
    ),
  );
  const input = host.querySelector<HTMLInputElement>('input[role="switch"]')!;
  expect(host.querySelector(".wu-switch")!.textContent).toBe("RemindersOff");
  expect(host.textContent).not.toContain("Enabled");
  act(() => input.click());
  expect(onToggle).toHaveBeenCalledWith(true);
  expect(onChange).not.toHaveBeenCalled();
});
it("keeps the switch off with a hint until the saved settings have a channel", () => {
  act(() =>
    root.render(
      <ScheduleEditor
        settings={{ ...settings, channel_id: "" }}
        channels={[]}
        disabled={false}
        onChange={vi.fn()}
      />,
    ),
  );
  const input = host.querySelector<HTMLInputElement>('input[role="switch"]')!;
  expect(input.disabled).toBe(true);
  expect(input.checked).toBe(false);
  expect(host.textContent).toContain("Select a channel first");
});
it("disables the switch while a save runs and shows its error beside it", () => {
  act(() =>
    root.render(
      <ScheduleEditor
        settings={settings}
        channels={[]}
        disabled={false}
        switchBusy
        switchError="Could not save. Try again."
        onChange={vi.fn()}
      />,
    ),
  );
  expect(
    host.querySelector<HTMLInputElement>('input[role="switch"]')!.disabled,
  ).toBe(true);
  expect(host.querySelector('[role="alert"]')!.textContent).toBe(
    "Could not save. Try again.",
  );
});
it("offers one phrasing for the audience and ends placeholders with an ellipsis", () => {
  act(() =>
    root.render(
      <ScheduleEditor
        settings={settings}
        channels={[]}
        disabled={false}
        onChange={vi.fn()}
      />,
    ),
  );
  expect(
    [...host.querySelectorAll("option")].map((o) => o.textContent),
  ).toContain("Players with no attacks used");
  expect(host.textContent).not.toContain("Only players who");
  expect(
    host.querySelector<HTMLInputElement>('input[type="number"]')!.placeholder,
  ).toBe("Example: 8…");
  expect(host.textContent).toContain("+ Add time");
});
