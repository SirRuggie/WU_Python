// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DashboardPermissions } from "./DashboardPermissions";
import RosterWorkspace from "./RosterWorkspace";
import CwlStepStrip from "./CwlStepStrip";
import type { PublicationDraft } from "./publication";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./SignupActivity", () => ({ default: () => null }));
vi.mock("./WeightQueue", () => ({ default: () => null }));
vi.mock("./CompareClans", () => ({ default: () => null }));
vi.mock("./ClanSettings", () => ({ default: () => null }));
vi.mock("./ConfirmDialog", () => ({
  default: ({ text }: any) => <div role="dialog">{text}</div>,
}));
it("Build loads draft state; signup warning and Fix remain in the header on every tab", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  sessionStorage.clear();
  localStorage.clear();
  const season = {
    id: 1,
    label: "November",
    status: "draft",
    signup_open: true,
  };
  api.mockImplementation(async (path: string) =>
    path === "/seasons"
      ? { seasons: [season], member_season: { season_id: 2, revision: 1 } }
      : path.endsWith("/publication")
        ? {
            published: null,
            last_publication: null,
            draft_changed: false,
            preview: { assigned_count: 125 },
          }
        : { revision: 1, clans: [], accounts: [], metadata_updating: false },
  );
  function Harness() {
    const [draft, setDraft] = useState<PublicationDraft | null>(null);
    return (
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <CwlStepStrip
          step="build"
          draft={draft}
          onBuild={() => {}}
          onFinalize={() => {}}
          onAnnounce={() => {}}
        />
        <RosterWorkspace
          seasonId="1"
          seasons={[season]}
          onSeasonChange={() => {}}
          onPublication={setDraft}
        />
      </DashboardPermissions.Provider>
    );
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<Harness />));
    expect(api).toHaveBeenCalledWith("/seasons/1/publication");
    expect(
      host.querySelector('[aria-label="Unpublished changes"]'),
    ).not.toBeNull();
    for (const label of [
      "Accounts & signups",
      "Compare clans",
      "Clan settings",
      "Missing weights",
    ]) {
      const tab = [
        ...host.querySelectorAll<HTMLButtonElement>(
          ".roster-workflow-nav button",
        ),
      ].find((b) => b.textContent?.includes(label))!;
      await act(async () => tab.click());
      expect(
        host.querySelector(".roster-header .staff-signup-controls")
          ?.textContent,
      ).toContain("Signups open · not visible to members");
    }
    const fix = [...host.querySelectorAll("button")].find(
      (b) => b.textContent?.trim() === "Fix ›",
    )!;
    await act(async () => fix.click());
    expect(host.querySelector('[role="dialog"]')?.textContent).toContain(
      "Show it to members?",
    );
    expect(api.mock.calls.every((c) => !c[1])).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
