// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from "vitest";
import {
  lifecycleSeason,
  lifecycleStepStates,
  loadLifecycleReadiness,
} from "./seasonLifecycle";
import { sortSignupAccounts } from "./signup";
import { defaultStaffSeason, monthSeasons } from "./seasonLabels";
import type { Account, Season } from "./api";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (load) => ({ ...(await load<object>()), api }));
const nov: Season = {
  id: 2,
  label: "2026-11",
  cwl_month: "2026-11",
  status: "draft",
  signup_open: false,
};
const dec: Season = { ...nov, id: 5, label: "December 2026", cwl_month: null };
beforeEach(() => {
  api.mockReset();
});
it("anchors explicit member ID, falls back only for NULL and excludes history/archived", () => {
  const seasons = [
    nov,
    dec,
    { ...nov, id: 9, label: "2027-01", history_only: true },
    { ...nov, id: 10, label: "2027-02", status: "archived" },
  ];
  expect(lifecycleSeason(seasons, 2)).toBe(nov);
  expect(lifecycleSeason(seasons, null)).toBe(dec);
  expect(lifecycleSeason(seasons, 777)).toBeUndefined();
  expect(
    lifecycleSeason([{ ...nov, status: "archived" }], null),
  ).toBeUndefined();
});
it("all menu/default helpers sort display month labels newest-first, history omitted by default", () => {
  const history = {
    ...nov,
    id: 99,
    label: "January 2027",
    cwl_month: null,
    history_only: 1,
  };
  const unknown = { ...nov, id: 100, label: "Other", cwl_month: null };
  expect(monthSeasons([nov, unknown, dec, history]).map((s) => s.id)).toEqual([
    99, 5, 2, 100,
  ]);
  expect(defaultStaffSeason([nov, history, dec])).toBe("5");
  expect(defaultStaffSeason([history])).toBe("");
  expect(monthSeasons([dec, { ...dec, id: 7 }]).map((s) => s.id)).toEqual([
    7, 5,
  ]);
});
it("sorts signup display only by TH high to low, case-insensitive name and no-TH last", () => {
  const accounts = [
    { tag: "a", name: "z", town_hall: null },
    { tag: "b", name: "beta", town_hall: 17 },
    { tag: "c", name: "Alpha", town_hall: 17 },
    { tag: "d", name: "Zeta", town_hall: 18 },
  ] as Account[];
  expect(sortSignupAccounts(accounts).map((a) => a.tag)).toEqual([
    "d",
    "c",
    "b",
    "a",
  ]);
  expect(accounts.map((a) => a.tag)).toEqual(["a", "b", "c", "d"]);
});
const clan = {
  tag: "#CLAN",
  name: "Fixture clan",
  active: true,
  candidates: 1,
  meets_rule: 1,
  results_state: "captured",
  allowance_ready: true,
  draw_state: "sent",
};
function reads(status = clan, changed = false) {
  api.mockImplementation(async (path: string) =>
    path.endsWith("/publication")
      ? {
          preview: { accounts: [{ pool: "main" }] },
          published: { version: 1 },
          draft_changed: changed,
        }
      : {
          season_id: 2,
          cycle: "2026-11",
          main_minimum: 1,
          pools: { main: [status], lazy: [] },
        },
  );
}
it("reuses captured/sent bonus workflow; gold uses existing published version regardless of draft changes", async () => {
  reads();
  expect(await loadLifecycleReadiness(2)).toEqual({
    published: true,
    blockers: [],
  });
  reads(clan, true);
  expect((await loadLifecycleReadiness(2)).published).toBe(true);
});
it("blocks missing/unfinished results and bonuses instead of treating absence as done", async () => {
  reads({ ...clan, results_state: "not_checked", draw_state: "none" });
  expect((await loadLifecycleReadiness(2)).blockers).toEqual([
    "Fixture clan: results",
    "Fixture clan: bonuses",
  ]);
  api.mockResolvedValue({});
  await expect(loadLifecycleReadiness(2)).rejects.toThrow();
});

it("no published version keeps Start secondary even with complete bonus results", async () => {
  reads();
  const original = api.getMockImplementation()!;
  api.mockImplementation(async (path: string) => {
    const result = await original(path);
    return path.endsWith("/publication")
      ? { ...result, published: null }
      : result;
  });
  expect((await loadLifecycleReadiness(2)).published).toBe(false);
});

it("lifecycle keeps unknown prior transitions Not recorded without inventing an opened history", () => {
  const closed = lifecycleStepStates(dec, true, false);
  expect(closed.find((s) => s.label === "Signups open")?.state).toBe(
    "Not recorded",
  );
  expect(closed.find((s) => s.label === "Signups closed")?.state).toBe(
    "Current",
  );
  const published = lifecycleStepStates(dec, true, true);
  expect(published.find((s) => s.label === "Published")?.state).toBe("Current");
  const locked = lifecycleStepStates(
    { ...dec, status: "archived" },
    true,
    true,
  );
  expect(locked.find((s) => s.label === "Locked")?.state).toBe("Current");
  expect(locked.find((s) => s.label === "Signups open")?.state).toBe(
    "Not recorded",
  );
});

import {
  readStartOperation,
  saveStartOperation,
  clearStartOperation,
} from "./seasonStartRecovery";
it("Start recovery is actor-bound, validated, cleared on identity/permission reset, and never performs requests", () => {
  const context = {
    actor: "staff-a",
    cycle: "2027-01",
    openSignups: true,
    seen: { season_id: 2, revision: 3 },
  };
  expect(saveStartOperation(context)).toBe(true);
  expect(readStartOperation("staff-a")).toEqual(context);
  expect(readStartOperation("staff-b")).toBeNull();
  clearStartOperation(undefined, "staff-b");
  expect(readStartOperation("staff-a")).toBeNull();
  saveStartOperation(context);
  clearStartOperation("staff-a");
  expect(readStartOperation("staff-a")).toBeNull();
  expect(api).not.toHaveBeenCalled();
});
