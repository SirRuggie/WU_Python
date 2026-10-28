import { beforeEach, expect, it, vi } from "vitest";
import {
  applySignupPlan,
  createSeasonConfirmation,
  createdSeasonMessage,
  signupPlan,
  type SeasonState,
} from "./seasonFlow";
import type { Season } from "./api";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));
const season = {
  id: 2,
  label: "November 2026",
  signup_open: false,
  status: "draft",
} as Season;
const state: SeasonState = {
  seasons: [season],
  member_season: { season_id: 1, revision: 7 },
};
beforeEach(() => api.mockReset());
it("confirms inheritance without guessing a count; first season starts empty", () => {
  expect(createSeasonConfirmation(season.label, false)).toBe(
    "November 2026 will start with the hosting clans and their settings from the previous season. Signups start empty.",
  );
  expect(createSeasonConfirmation(season.label, true)).toBe(
    "November 2026 will start with no hosting clans.",
  );
  expect(createdSeasonMessage(season.label, 3)).toBe(
    "November 2026 created with 3 hosting clans and their settings. Signups start empty.",
  );
});
it("asks to show and open a hidden season, in that order with both guards", async () => {
  expect(signupPlan(season, state, "open").label).toBe("Show and open");
  await applySignupPlan(season, state, "open");
  expect(api.mock.calls).toEqual([
    ["/member-season", "PUT", { season_id: 2, revision: 7 }],
    ["/seasons/2", "PATCH", { signup_open: true, expected_signup_open: false }],
  ]);
});
it("reports a partial failure and never retries either write", async () => {
  api
    .mockResolvedValueOnce({})
    .mockRejectedValueOnce(new Error("409: changed"));
  await expect(applySignupPlan(season, state, "open")).rejects.toThrow(
    "Shown to members; signups not opened: 409: changed",
  );
  expect(api).toHaveBeenCalledTimes(2);
});
it("close only sends its compare-and-set, never changes visibility", async () => {
  await applySignupPlan({ ...season, signup_open: true }, state, "close");
  expect(api.mock.calls).toEqual([
    ["/seasons/2", "PATCH", { signup_open: false, expected_signup_open: true }],
  ]);
});
it("Fix sends no signup PATCH; a freshly closed season instead shows and opens", async () => {
  await applySignupPlan({ ...season, signup_open: true }, state, "fix");
  expect(api.mock.calls).toEqual([
    ["/member-season", "PUT", { season_id: 2, revision: 7 }],
  ]);
  api.mockClear();
  await applySignupPlan(season, state, "fix");
  expect(api).toHaveBeenCalledTimes(2);
});
it("a visibility conflict stops before opening signups", async () => {
  api.mockRejectedValueOnce(new Error("409: member season changed"));
  await expect(applySignupPlan(season, state, "open")).rejects.toThrow(
    "409: member season changed",
  );
  expect(api).toHaveBeenCalledTimes(1);
});
it("already visible opening does not write the member season", async () => {
  await applySignupPlan(
    season,
    { ...state, member_season: { season_id: 2, revision: 7 } },
    "open",
  );
  expect(api.mock.calls).toEqual([
    ["/seasons/2", "PATCH", { signup_open: true, expected_signup_open: false }],
  ]);
});
