import { beforeEach, expect, it, vi } from "vitest";
import { finishMonth } from "./seasonFlow";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
const nov = { id: 4, label: "2026-11", signup_open: false, status: "draft" };
const dec = { id: 5, label: "2026-12", signup_open: false, status: "draft" };
const base = { seasons: [nov], member_season: { season_id: 4, revision: 3 } };
const withDec = { seasons: [nov, dec], member_season: base.member_season };
const callsOf = () =>
  api.mock.calls.map((call) => `${call[1] ?? "GET"} ${call[0]}`);
beforeEach(() => api.mockReset());

it("finishes in order: create, show, then open signups when asked", async () => {
  api.mockResolvedValueOnce(base).mockResolvedValueOnce({});
  api.mockResolvedValueOnce(withDec).mockResolvedValue({});
  await finishMonth("2026-12", true);
  expect(callsOf()).toEqual([
    "GET /seasons",
    "POST /seasons",
    "GET /seasons",
    "PUT /member-season",
    "PATCH /seasons/5",
  ]);
  expect(api).toHaveBeenCalledWith("/seasons", "POST", {
    label: "2026-12",
    signup_open: false,
  });
  expect(api).toHaveBeenCalledWith("/member-season", "PUT", {
    season_id: 5,
    revision: 3,
  });
  expect(api).toHaveBeenLastCalledWith("/seasons/5", "PATCH", {
    signup_open: true,
    expected_signup_open: false,
  });
});

it("does not open signups when the box is off", async () => {
  api.mockResolvedValueOnce(withDec).mockResolvedValue({});
  await finishMonth("2026-12", false);
  expect(callsOf()).toEqual(["GET /seasons", "PUT /member-season"]);
});

it("reports completed steps on failure; a retry does not create twice", async () => {
  api.mockResolvedValueOnce(base).mockResolvedValueOnce({});
  api
    .mockResolvedValueOnce(withDec)
    .mockRejectedValueOnce(new Error("Revision changed."));
  await expect(finishMonth("2026-12", true)).rejects.toThrow(
    "Revision changed. Done: create December 2026. Not done: show December 2026 to members, open December 2026 signups.",
  );
  api.mockReset();
  api.mockResolvedValueOnce(withDec).mockResolvedValue({});
  await finishMonth("2026-12", true);
  expect(callsOf()).toEqual([
    "GET /seasons",
    "PUT /member-season",
    "PATCH /seasons/5",
  ]);
});
