import { describe, it, expect } from "vitest";
import {
  deliveryLabel,
  destinationIssue,
  rowHealth,
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
      "removed or become inaccessible",
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
      "removed or become inaccessible",
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
    expect(deliveryLabel("sending")).toContain("check the channel before acting");
    expect(deliveryLabel("uncertain")).toContain("check the channel before acting");
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
});
