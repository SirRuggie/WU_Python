import { expect, it } from "vitest";
import initial from "../../tests/fixtures/signup-reminders-data.json";
import type { Campaign, Occurrence } from "../reminderCampaign";
import {
  initialEditorPool,
  reminderRows,
  visibleReminderRows,
} from "./reminderList";
import {
  targetCwlMonth,
  shortReminderTime,
  reminderStatusLabel,
} from "./reminderFormat";
const lookups = {
  channels: {
    items: [{ id: "channel-main" }, { id: "channel-lazy" }],
    loading: false,
    error: "",
  },
  roles: {
    items: [{ id: "role-main" }, { id: "role-lazy" }],
    loading: false,
    error: "",
  },
};
it("keeps one row per message, excludes roster and selects the sole error pool", () => {
  const draft = structuredClone(initial) as Campaign;
  expect(reminderRows(draft, "all", lookups, [], true)).toHaveLength(6);
  expect(initialEditorPool(draft, "signup", "all", lookups)).toBe("main");
  draft.messages.signup.variants.lazy.title = "";
  expect(initialEditorPool(draft, "signup", "all", lookups)).toBe("lazy");
  draft.messages.signup.variants.main.title = "";
  expect(initialEditorPool(draft, "signup", "all", lookups)).toBe("main");
  expect(initialEditorPool(draft, "signup", "lazy", lookups)).toBe("lazy");
});
it("sorts next visible enabled time first, no time last, then natural names", () => {
  const draft = structuredClone(initial) as Campaign;
  draft.messages.signup.label = "Reminder 10";
  draft.messages["reminder:2"].label = "Reminder 9";
  const schedule = [
    {
      id: "future",
      message_id: "reminder:2",
      variant: "lazy",
      run_at: "2090-01-01T00:00:00Z",
    },
  ] as Occurrence[];
  const rows = reminderRows(draft, "all", lookups, schedule, true);
  expect(
    visibleReminderRows(rows, { hasError: false, off: false }, "send_time")[0]
      .id,
  ).toBe("reminder:2");
  const names = visibleReminderRows(
    rows,
    { hasError: false, off: false },
    "name",
  ).map((row) => row.message.label);
  expect(names.indexOf("Reminder 9")).toBeLessThan(
    names.indexOf("Reminder 10"),
  );
  expect(
    reminderRows(draft, "main", lookups, schedule, true).every(
      (row) => !row.next,
    ),
  ).toBe(true);
  expect(
    reminderRows(draft, "all", lookups, schedule, false).every(
      (row) => !row.next,
    ),
  ).toBe(true);
  draft.messages["reminder:2"].variants.lazy.enabled = false;
  expect(
    reminderRows(draft, "all", lookups, schedule, true).every(
      (row) => !row.next,
    ),
  ).toBe(true);
});
it("intersects error and Off filters without mutating or dropping draft messages", () => {
  const draft = structuredClone(initial) as Campaign;
  draft.messages.signup.variants.lazy.enabled = false;
  draft.messages.signup.variants.main.title = "";
  const before = JSON.stringify(draft);
  const rows = reminderRows(draft, "all", lookups, [], true);
  expect(
    visibleReminderRows(rows, { hasError: true, off: true }, "name").map(
      (row) => row.id,
    ),
  ).toEqual(["signup"]);
  expect(JSON.stringify(draft)).toBe(before);
});
it("formats one target month and never exposes raw schedule statuses", () => {
  expect(targetCwlMonth("2026-11")).toBe("December 2026");
  expect(targetCwlMonth("2026-12")).toBe("January 2027");
  expect(targetCwlMonth("2026-13")).toContain("unavailable");
  expect(shortReminderTime("invalid")).toBe("Time unavailable");
  expect(shortReminderTime()).toBe("Not scheduled");
  expect(
    [
      "scheduled",
      "pending",
      "sent",
      "skipped",
      "paused",
      "inactive",
      "uncertain",
      "private-api-status",
    ].map(reminderStatusLabel),
  ).toEqual([
    "Upcoming",
    "Upcoming",
    "Sent",
    "Skipped",
    "Paused",
    "Not scheduled",
    "Check History",
    "Check History",
  ]);
});
