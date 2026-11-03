import { expect, it } from "vitest";
import {
  reminderHistoryDetail,
  reminderHistoryStatus,
  reminderHistoryTitle,
} from "./reminderHistory";

it("shows plain history labels without raw delivery codes or lower-case audiences", () => {
  expect(reminderHistoryStatus({ status: "sent", variant: "lazy" })).toBe(
    "Lazy · Sent",
  );
  expect(
    reminderHistoryStatus({ status: "deleted_confirmed", variant: "main" }),
  ).toBe("Main · Post deleted");
  expect(
    reminderHistoryStatus({ status: "sent", late: true, variant: "main" }),
  ).toBe("Main · Sent late");
  expect(
    reminderHistoryStatus({
      status: "skipped",
      reason: "Skipped: too late",
      variant: "lazy",
    }),
  ).toBe("Lazy · Skipped: too late");
  expect(
    reminderHistoryStatus({
      status: "skipped",
      reason: "Skipped: too close to another send",
    }),
  ).toBe("Skipped: too close to another send");
  expect(reminderHistoryStatus({ status: "uncertain" })).toBe("Check Discord");
});

it("uses reminder names, never raw Discord message IDs or unknown status enums", () => {
  expect(
    reminderHistoryTitle({
      message_id: "123456789012345678",
      occurrence_id: "2026-11|signup|main",
    }),
  ).toBe("Signup message");
  expect(reminderHistoryTitle({ message_key: "reminder:10" })).toBe(
    "Reminder 10",
  );
  expect(reminderHistoryTitle({ message_key: "roster" })).toBe("Roster post");
  expect(reminderHistoryTitle({ message_id: "123456789012345678" })).toBe(
    "Reminder activity",
  );
  expect(
    reminderHistoryStatus({
      status: "unknown_internal_value",
      variant: "unknown",
    }),
  ).toBe("Audience unavailable · Status unavailable");
  expect(reminderHistoryStatus({ action: "paused" })).toBe("Paused");
  for (const value of ["__proto__", "constructor", "toString"])
    expect(reminderHistoryStatus({ status: value, action: value })).toBe(
      "Status unavailable",
    );
});

it("retains useful detail without inventing a scheduled timestamp", () => {
  expect(
    reminderHistoryDetail({
      status: "sent",
      late: true,
      original_due_at: "2026-11-20T12:00:00Z",
    }),
  ).toEqual({ scheduled: "2026-11-20T12:00:00Z" });
  expect(
    reminderHistoryDetail({
      status: "sent",
      late: true,
      original_due_at: "bad date",
    }),
  ).toBeNull();
  expect(
    reminderHistoryDetail({ status: "skipped", reason: "Skipped: too late" }),
  ).toBeNull();
  expect(
    reminderHistoryDetail({
      status: "uncertain",
      reason: "Not sure it sent. Check Discord.",
    }),
  ).toEqual({ reason: "Not sure it sent. Check Discord." });
});

it("does not prepend a second skipped label to legacy spacing history", () => {
  const reason = "Skipped an overdue reminder to preserve the minimum spacing.";
  expect(
    reminderHistoryStatus({ status: "skipped", variant: "lazy", reason }),
  ).toBe(`Lazy · ${reason}`);
});
