import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import DeliveryHistory, {
  DeliveryStatus,
  historySummary,
} from "./DeliveryHistory";
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
describe("Reminder status and history", () => {
  it("keeps current status visible with one short line about who is named", () => {
    const html = renderToStaticMarkup(<DeliveryStatus data={data} enabled />);
    expect(html).toContain("Tracking current war.");
    expect(html).toContain(
      "Each player is named once, with only their accounts that have attacks left.",
    );
    expect(html).not.toContain("<details");
    expect(html).not.toMatch(/the bot/i);
  });
  it("does not imply disabled reminders are tracking", () => {
    const html = renderToStaticMarkup(
      <DeliveryStatus data={data} enabled={false} />,
    );
    expect(html).toContain("Automatic reminders are disabled.");
    expect(html).not.toContain("Tracking current war.");
  });
  it("waits for the first check in plain words", () => {
    const html = renderToStaticMarkup(
      <DeliveryStatus data={{ ...data, status: null }} enabled />,
    );
    expect(html).toContain("Waiting for the first check.");
  });
  it("flags unresolved deliveries in the closed summary only when they exist", () => {
    expect(historySummary(data)).toBe("Test & history · 1 need review");
    expect(
      historySummary({
        ...data,
        history: [{ ...data.history[0], status: "sent" }],
      }),
    ).toBe("Test & history");
    expect(historySummary({ ...data, history: [] })).toBe("Test & history");
  });
});

it("labels outcomes visibly without inventing a reason for skipped reminders", () => {
  const html = renderToStaticMarkup(
    <DeliveryHistory
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
it("explains an empty history", () => {
  const html = renderToStaticMarkup(
    <DeliveryHistory data={{ ...data, history: [] }} />,
  );
  expect(html).toContain("No deliveries yet");
});

it("shows a gold maintenance notice in the editor without implying an error", () => {
  const maintenance: ReminderData = {
    ...data,
    history: [],
    health: {
      category: "maintenance",
      label: "Clash maintenance",
      detail: "Reminders continue when it ends.",
    },
  };
  const html = renderToStaticMarkup(
    <DeliveryStatus data={maintenance} enabled />,
  );
  expect(html).toContain('class="notice reminder-maintenance"');
  expect(html).toContain("Clash maintenance");
  expect(html).toContain("Reminders continue when it ends.");
  expect(html).not.toContain('role="alert"');
  expect(
    renderToStaticMarkup(<DeliveryStatus data={maintenance} enabled={false} />),
  ).not.toContain("Clash maintenance");
});

it.each(["uncertain", "sending"])(
  "keeps %s delivery health visible ahead of maintenance status",
  (status) => {
    const blocked: ReminderData = {
      ...data,
      status: {
        checked_at: "2026-01-01T00:00:00Z",
        detail: "Clash maintenance. Reminders continue when it ends.",
      },
      history: [{ ...data.history[0], status }],
      health: {
        category: "attention",
        label: "Check delivery",
        detail:
          "The last scheduled delivery was not confirmed. Check the channel before taking action.",
      },
    };
    const html = renderToStaticMarkup(
      <DeliveryStatus data={blocked} enabled />,
    );
    expect(html).toContain("Check delivery");
    expect(html).toContain("not confirmed");
    expect(html).not.toContain("Clash maintenance");
    expect(html).not.toContain("reminder-maintenance");
  },
);
