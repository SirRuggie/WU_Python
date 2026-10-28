import { expect, it } from "vitest";
import {
  announcementDeliveryStatus,
  announcementPublicationStatus,
} from "./announcementDelivery";
import type { ManageDelivery } from "./manageBridge";
import { publicationDate } from "./publicationStatus";
it.each([
  [null, "Not announced yet"],
  [{ status: "pending" }, "Queued · waiting for the bot"],
  [{ status: "sending" }, "Sending…"],
  [{ status: "failed", error: "Channel missing" }, "Failed · Channel missing"],
  [
    { status: "uncertain" },
    "Check Discord first: it may have posted. Resending is blocked.",
  ],
  [
    { status: "stale" },
    "Message settings changed since it was queued · review and retry",
  ],
] as [ManageDelivery | null, string][])("plain status %j", (value, text) =>
  expect(announcementDeliveryStatus(value, 2)).toBe(text),
);
it("distinguishes older published versions without implying automatic resend", () => {
  const sent = {
    status: "sent" as const,
    sent_at: "2026-10-27T13:10:00Z",
    publication_version: 1,
  };
  expect(announcementDeliveryStatus(sent, 1)).toBe(
    `Sent ${publicationDate(sent.sent_at)}`,
  );
  expect(announcementDeliveryStatus(sent, 2)).toBe(
    `Sent ${publicationDate(sent.sent_at)} for version 1 · Members now see version 2 through the roster link. Announcements aren't resent.`,
  );
  expect(
    announcementDeliveryStatus({ ...sent, publication_version: null }, 2),
  ).not.toContain("for version");
  expect(announcementDeliveryStatus({ ...sent, sent_at: "bad" }, 1)).toBe(
    "Sent",
  );
});
it("shares the never-published, hidden and publication wording", () => {
  expect(announcementPublicationStatus(undefined)).toBe(
    "Checking publication status…",
  );
  expect(
    announcementPublicationStatus({ published: null, last_publication: null }),
  ).toBe("Publish the roster before announcing");
  const last = {
    version: 1,
    published_at: "2026-10-27T13:10:00Z",
    withdrawn_at: "2026-10-28T13:10:00Z",
    joining_instructions: "",
  };
  expect(
    announcementPublicationStatus({ published: null, last_publication: last }),
  ).toBe(
    `Hidden from members · last published version 1 on ${publicationDate(last.published_at)}`,
  );
  expect(publicationDate(last.published_at)).not.toMatch(/\d+:\d+:\d+/);
});
