// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import StrikeActivityDetail from "./StrikeActivityDetail";
import { compactActivitySummary } from "./StrikeActivityRows";
import type { ActivityAccount } from "./strikeActivityView";
it("keeps full evidence and war-end precision in details", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <StrikeActivityDetail
          account={{
            observed_wars: 14,
            attacked_wars: 2,
            no_attack_wars: 5,
            missed_attacks: 10,
            observed_attacks: 28,
            observed_raid_weekends: 1,
            attacked_raid_weekends: 0,
            last_attacked_war_end: "2026-10-30T12:00:00Z",
            replacement_note: "<script>staff</script>",
          }}
        />,
      ),
    );
    expect(host.textContent).toContain("Attacked in 2 of 14 known wars");
    expect(host.textContent).toContain("Missed 10 of 28 observed war attacks");
    expect(host.textContent).toContain("not the exact attack time");
    expect(host.textContent).toContain("another weekend is unavailable");
    expect(host.querySelector("script")).toBeNull();
    await act(async () =>
      root.render(
        <StrikeActivityDetail
          account={{
            activity_unavailable: true,
            observed_wars: 14,
            attacked_wars: 0,
            no_attack_wars: 14,
            quiet_days: 99,
          }}
        />,
      ),
    );
    expect(host.textContent).not.toContain("last 14 known wars");
    expect(host.textContent).not.toContain("Quiet for 99");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
it("compact summaries never turn missing observations into zero activity", () => {
  const unknown = {
    activity_unavailable: true,
    no_attack_wars: 0,
    quiet_days: 0,
  } as ActivityAccount;
  expect(compactActivitySummary(unknown)).toBe("");
  expect(
    compactActivitySummary({
      ...unknown,
      activity_unavailable: false,
      observed_wars: 14,
      no_attack_wars: 0,
      last_seen_at: "2026-10-31T12:00:00Z",
    }),
  ).not.toContain("last 0 wars");
});
it("uses the consecutive missed-war chain and preserves known ratios at zero", () => {
  const row = { observed_wars: 14, attacked_wars: 7, no_attack_wars: 0 } as ActivityAccount;
  expect(compactActivitySummary(row)).toBe("7 of 14 wars");
  expect(compactActivitySummary({ ...row, no_attack_wars: 1 })).toBe("Missed last war");
  expect(compactActivitySummary({ ...row, no_attack_wars: 14 })).toBe("Missed last 14 wars");
  expect(compactActivitySummary({ ...row, activity_unavailable: true })).toBe("");
});
