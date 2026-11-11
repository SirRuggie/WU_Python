// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import ParticipationWorkspace from "./ParticipationWorkspace";
import { syncStatusLabel } from "./participation";
const fixture = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: fixture.api,
}));
vi.mock("./ParticipationRecord", () => ({
  default: ({ account }: { account: { player_name: string } }) => (
    <p>{account.player_name}</p>
  ),
}));
afterEach(() => {
  fixture.api.mockReset();
  localStorage.clear();
  sessionStorage.clear();
  document.body.replaceChildren();
});
it.each([
  ["waiting", "November CWL has not started in Clash yet", false],
  [
    "season_mismatch",
    "Clash reports a later CWL month than the selected month",
    true,
  ],
  ["partial", "CWL observations are incomplete", false],
  ["unavailable", "Clash could not be refreshed", true],
  ["complete", null, false],
] as const)(
  "keeps %s distinct from ordinary waiting",
  async (status, warning, hasProblem) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const account = {
      tag: "#P2Y",
      player_name: "Fixture player",
      town_hall: 16,
      pool: "main",
      assigned_clan_tag: "#C2Y",
      assigned_clan_name: "Fixture clan",
      attacks: null,
      stars: null,
      notes: "",
      revision: 0,
      updated_by: null,
      updated_at: null,
      in_latest_publication: true,
      source_status: status === "complete" ? "complete" : "unavailable",
      source_complete: status === "complete",
      display_status: {
        code: status === "partial" ? "in_progress" : status,
        label: status === "partial" ? "CWL in progress" : status === "complete" ? "Complete"
          : status === "waiting" ? "CWL has not started" : status === "season_mismatch" ? "CWL month mismatch" : "Results unavailable",
        warning: status === "season_mismatch" ? warning : status === "unavailable" ? "This clan could not refresh. No saved results are available." : null,
        failed_clan: status === "unavailable",
        round: status === "partial" ? 2 : null,
      },
    };
    fixture.api.mockResolvedValue({
      publication_version: 1,
      accounts: [account],
      sync: {
        cycle: "2026-11",
        cycle_source: "settings",
        enabled: true,
        status,
        warning,
        last_checked_at: "2026-11-01T12:00:00Z",
        last_success_at: null,
        updated_at: "2026-11-01T12:00:00Z",
      },
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const next = vi.fn();
    try {
      await act(async () => {
        root.render(
          <ParticipationWorkspace
            onBonus={next}
            seasonId="1"
            seasons={[
              {
                id: 1,
                label: "November 2026",
                status: "draft",
                signup_open: true,
              },
            ]}
            onSeasonChange={() => {}}
          />,
        );
      });
      // Prompt 228: the step bar replaces the bottom "Next: Bonus medals" cue.
      expect(host.querySelectorAll(".cwl-next-cue")).toHaveLength(0);
      expect(host.querySelectorAll(".bonus-step-bar")).toHaveLength(1);
      const beforeCalls = fixture.api.mock.calls.length;
      await act(async () =>
        (
          host.querySelector(
            '.bonus-step[data-step="eligibility"] a',
          ) as HTMLAnchorElement
        ).click(),
      );
      expect(next).toHaveBeenCalledExactlyOnceWith(
        "pool=main&step=eligibility",
      );
      expect(fixture.api.mock.calls).toHaveLength(beforeCalls);
      const text = host.textContent || "";
      expect(
        host.querySelector(".participation-capture")?.textContent,
      ).toContain("November 2026");
      expect(
        host.querySelector(".participation-capture")?.textContent,
      ).not.toContain("2026-11");
      expect(text).not.toContain("incomplete, stale or unavailable source results.");
      const problems = host.querySelectorAll(".participation-capture-warning");
      expect(problems.length > 0).toBe(hasProblem);
      if (status === "partial") {
        expect(text).toContain("CWL in progress · round 2 of 7");
        // Prompt164 removes the duplicate capture count; list scope stays visible.
        // Prompt 228 counts the selected pool only.
        expect(text).toContain("1 player · Main CWL");
        expect(host.querySelector(".participation-capture")?.textContent)
          .not.toContain("current signups in this view");
        expect(text).not.toContain("CWL observations are incomplete");
      }
      if (status === "unavailable") {
        expect(text).toContain("1 clan could not refresh: Fixture clan. No saved results yet for 1 account in this view.");
        expect(text).not.toContain("Showing last saved results");
      }
      if (status === "waiting") {
        expect(
          text.split("November CWL has not started in Clash yet"),
        ).toHaveLength(2);
        expect(text).not.toContain("CWL month mismatch");
        expect(host.querySelector('[role="alert"]')).toBeNull();
      } else {
        expect(text).not.toContain("has not started in Clash yet");
        if (status === "season_mismatch" && warning) expect(text).toContain(warning);
      }
      expect(
        fixture.api.mock.calls.every(
          (call) => call[1] === undefined || call[1] === "GET",
        ),
      ).toBe(true);
    } finally {
      await act(async () => root.unmount());
    }
  },
);
it("names the selected month and never reinterprets a real mismatch by calendar alone", () => {
  expect(syncStatusLabel("waiting", "2027-01")).toBe(
    "January CWL has not started in Clash yet",
  );
  expect(syncStatusLabel("season_mismatch", "2026-11")).toBe(
    "CWL month mismatch",
  );
  expect(syncStatusLabel("waiting", "not-a-month")).toBe(
    "Waiting for Clash CWL",
  );
});
