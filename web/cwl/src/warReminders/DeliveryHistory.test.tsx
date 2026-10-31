import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import DeliveryHistory from "./DeliveryHistory";
import type { ReminderData } from "./types";
const data: ReminderData = {
  settings: {
    enabled: true,
    channel_id: "123",
    minutes: [60],
    war_started: true,
    audience: "remaining",
  },
  revision: "1",
  status: {
    detail: "Tracking current war.",
    checked_at: "2026-10-21T12:00:00Z",
  },
  history: [
    {
      at: "2026-10-21T12:00:00Z",
      event: "60",
      test: false,
      status: "uncertain",
      detail: "Check the channel.",
    },
  ],
};
describe("Collapsed delivery history", () => {
  it("keeps current status and unresolved delivery counts discoverable", () => {
    const html = renderToStaticMarkup(<DeliveryHistory data={data} enabled />);
    expect(html.split("<details")[0]).toContain("Tracking current war.");
    expect(html).toContain(
      "<summary>Delivery history · 1 need review</summary>",
    );
    expect(html).not.toMatch(/<details[^>]*\bopen/);
  });
  it("does not imply disabled reminders are tracking or successful sends need review", () => {
    const html = renderToStaticMarkup(
      <DeliveryHistory
        data={{ ...data, history: [{ ...data.history[0], status: "sent" }] }}
        enabled={false}
      />,
    );
    expect(html).toContain("Automatic reminders are disabled.");
    expect(html).not.toContain("Tracking current war.");
    expect(html).toContain("<summary>Delivery history · 1 recent</summary>");
  });
});

it("labels outcomes visibly without inventing a reason for skipped reminders", () => {
  const html = renderToStaticMarkup(
    <DeliveryHistory
      enabled
      data={{
        ...data,
        history: [
          {
            ...data.history[0],
            status: "sent",
            url: "https://discord.com/channels/1/2/3",
          },
          { ...data.history[0], status: "failed" },
          {
            ...data.history[0],
            status: "skipped",
            detail: "No players need a reminder.",
          },
          { ...data.history[0], status: "uncertain" },
        ],
      }}
    />,
  );
  for (const label of [
    "✓ Sent",
    "! Failed",
    "– Skipped",
    "? Uncertain",
    "No players need a reminder.",
  ])
    expect(html).toContain(label);
  expect(html).not.toContain("Skipped · too late");
  expect(html).toContain('class="war-delivery-link"');
});
