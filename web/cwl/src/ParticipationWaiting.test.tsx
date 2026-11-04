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
  ["partial", "CWL observations are incomplete", true],
  ["unavailable", "Clash could not be refreshed", true],
  ["complete", null, false],
] as const)(
  "keeps %s distinct from ordinary waiting",
  async (status, warning, incomplete) => {
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
      expect(host.querySelectorAll(".cwl-next-cue")).toHaveLength(1);
      const beforeCalls = fixture.api.mock.calls.length;
      await act(async () =>
        (host.querySelector(".cwl-next-cue") as HTMLButtonElement).click(),
      );
      expect(next).toHaveBeenCalledOnce();
      expect(fixture.api.mock.calls).toHaveLength(beforeCalls);
      const text = host.textContent || "";
      expect(
        host.querySelector(".participation-capture")?.textContent,
      ).toContain("November 2026");
      expect(
        host.querySelector(".participation-capture")?.textContent,
      ).not.toContain("2026-11");
      expect(
        text.includes("incomplete, stale or unavailable source results."),
      ).toBe(incomplete);
      if (status === "waiting") {
        expect(
          text.split("November CWL has not started in Clash yet"),
        ).toHaveLength(2);
        expect(text).not.toContain("CWL month mismatch");
        expect(host.querySelector('[role="alert"]')).toBeNull();
      } else {
        expect(text).not.toContain("has not started in Clash yet");
        if (warning) expect(text).toContain(warning);
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
