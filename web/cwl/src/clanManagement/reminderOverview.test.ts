import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import {
  deliveryLabel,
  destinationIssue,
  notSetUp,
  rowHealth,
  scheduleSummary,
  visibleRows,
  type OverviewRow,
} from "./reminderOverview";
const row: OverviewRow = {
  clan: { tag: "#ONE", name: "Alpha", type: "Main", logo: "", revision: "1" },
  settings: {
    enabled: true,
    channel_id: "123",
    minutes: [60],
    war_started: true,
    audience: "remaining",
  },
  revision: "rev-1",
  health: {
    category: "tracking",
    label: "Monitoring",
    detail: "Waiting for war",
  },
  checked_at: null,
  last_delivery: null,
};
describe("Family overview filters and honest states", () => {
  it("does not report missing channels when channel lookup is unavailable", () => {
    expect(rowHealth(row, new Set(), false).category).toBe("tracking");
    expect(rowHealth(row, new Set(), true).category).toBe("attention");
    expect(destinationIssue(row, new Set(), true)).toContain(
      "removed it, or Discord may not allow reminders there",
    );
    expect(
      rowHealth(
        {
          ...row,
          settings: { ...row.settings, enabled: false },
          health: { category: "off", label: "Off", detail: "Disabled" },
        },
        new Set(),
        true,
      ).category,
    ).toBe("off");
  });
  it("keeps a delivery or stale-check alert visible when the channel is missing", () => {
    const failed = {
      ...row,
      health: {
        category: "attention" as const,
        label: "Check delivery",
        detail: "Check the channel.",
      },
    };
    expect(rowHealth(failed, new Set(), true).label).toBe("Check delivery");
    expect(destinationIssue(failed, new Set(), true)).toContain(
      "removed it, or Discord may not allow reminders there",
    );
    expect(destinationIssue(row, new Set(), false)).toBeNull();
    expect(
      destinationIssue(
        { ...row, settings: { ...row.settings, enabled: false } },
        new Set(),
        true,
      ),
    ).toBeNull();
  });
  it("labels last scheduled outcomes without turning skipped reminders into failures", () => {
    expect(deliveryLabel("sending")).toContain(
      "check the channel before acting",
    );
    expect(deliveryLabel("uncertain")).toContain(
      "check the channel before acting",
    );
    expect(deliveryLabel("failed")).toBe("Failed");
    expect(deliveryLabel("skipped")).toBe("Skipped");
  });
  it("searches channel names and tags without mutating the source order", () => {
    const rows = [
      row,
      {
        ...row,
        clan: { ...row.clan, tag: "#TWO", name: "Beta" },
        health: {
          category: "attention" as const,
          label: "Check failed",
          detail: "Failure",
        },
      },
    ];
    expect(
      visibleRows(rows, "", "all", new Map([["123", "war-room"]]), true)[0].clan
        .name,
    ).toBe("Beta");
    expect(rows[0].clan.name).toBe("Alpha");
    expect(visibleRows(rows, " #two ", "all", new Map(), false)).toHaveLength(
      1,
    );
    expect(
      visibleRows(
        rows,
        "war-room",
        "all",
        new Map([["123", "war-room"]]),
        true,
      ),
    ).toHaveLength(2);
  });
  it("keeps disabled, enabled, and attention filtering distinct", () => {
    const off = {
      ...row,
      clan: { ...row.clan, tag: "#OFF" },
      settings: { ...row.settings, enabled: false },
      health: { category: "off" as const, label: "Off", detail: "Disabled" },
    };
    expect(visibleRows([row, off], "", "off", new Map(), false)).toEqual([off]);
    expect(visibleRows([row, off], "", "enabled", new Map(), false)).toEqual([
      row,
    ]);
    expect(visibleRows([row, off], "", "attention", new Map(), true)).toEqual([
      row,
    ]);
  });
  it("separates Off (has a channel) from Not set up (no channel)", () => {
    const off = {
      ...row,
      clan: { ...row.clan, tag: "#OFF" },
      settings: { ...row.settings, enabled: false },
      health: { category: "off" as const, label: "Off", detail: "Disabled" },
    };
    const unset = {
      ...row,
      clan: { ...row.clan, tag: "#NEW" },
      settings: { ...row.settings, enabled: false, channel_id: "" },
      health: {
        category: "not_configured" as const,
        label: "Not configured",
        detail: "",
      },
    };
    const all = [row, off, unset];
    expect(notSetUp(unset)).toBe(true);
    expect(notSetUp(off)).toBe(false);
    expect(visibleRows(all, "", "off", new Map(), false)).toEqual([off]);
    expect(visibleRows(all, "", "not_set_up", new Map(), false)).toEqual([
      unset,
    ]);
    expect(visibleRows(all, "", "enabled", new Map(), false)).toEqual([row]);
    expect(visibleRows(all, "", "all", new Map(), false)).toHaveLength(3);
  });
  it("filters by clan type and keeps attention first", () => {
    const cwl = {
      ...row,
      clan: { ...row.clan, tag: "#CWL", name: "Zed", type: "CWL" },
      health: {
        category: "attention" as const,
        label: "Check failed",
        detail: "",
      },
    };
    const farm = {
      ...row,
      clan: { ...row.clan, tag: "#FWA", name: "Beta", type: "Farming" },
    };
    expect(
      visibleRows([row, farm, cwl], "", "all", new Map(), false, "CWL"),
    ).toEqual([cwl]);
    expect(
      visibleRows([row, farm, cwl], "", "all", new Map(), false, "FWA"),
    ).toEqual([farm]);
    expect(
      visibleRows([row, farm, cwl], "", "all", new Map(), false).map(
        (item) => item.clan.tag,
      ),
    ).toEqual(["#CWL", "#ONE", "#FWA"]);
  });
  it("does not search by the raw channel ID", () => {
    expect(visibleRows([row], "123", "all", new Map(), true)).toEqual([]);
  });
  it("summarizes the schedule on one line", () => {
    expect(scheduleSummary(row.settings)).toBe("War start · 1h before end");
    expect(
      scheduleSummary({
        ...row.settings,
        war_started: false,
        minutes: [720, 480, 120, 60, 30],
      }),
    ).toBe("12h, 8h, 2h before end · +2 more");
    expect(
      scheduleSummary({ ...row.settings, war_started: false, minutes: [] }),
    ).toBe("No times selected");
  });
});

describe("Product wording", () => {
  it("never says the bot in the war reminder interface files", () => {
    for (const file of [
      "clanManagement/reminderOverview.ts",
      "clanManagement/ReminderOverview.tsx",
      "clanManagement/ReminderOverviewFilters.tsx",
      "warReminders/DeliveryHistory.tsx",
      "warReminders/ScheduleEditor.tsx",
      "WarReminders.tsx",
    ])
      expect(
        readFileSync(new URL(`../${file}`, import.meta.url), "utf8"),
        file,
      ).not.toMatch(/\bthe bot\b|bot’s/i);
  });
});
