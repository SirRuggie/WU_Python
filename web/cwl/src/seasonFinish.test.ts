import { beforeEach, expect, it, vi } from "vitest";
import { finishMonth } from "./seasonFlow";
const { api, readiness } = vi.hoisted(() => ({
  api: vi.fn(),
  readiness: vi.fn(),
}));
vi.mock("./api", async (load) => ({ ...(await load<object>()), api }));
vi.mock("./seasonLifecycle", () => ({ loadLifecycleReadiness: readiness }));
const nov = { id: 4, label: "2026-11", signup_open: false, status: "draft" };
const dec = { id: 5, label: "2026-12", signup_open: false, status: "draft" };
const seen = { season_id: 4, revision: 3 };
let state = { seasons: [nov], member_season: seen };
beforeEach(() => {
  state = { seasons: [nov], member_season: seen };
  api.mockReset();
  readiness.mockReset();
  readiness.mockResolvedValue({ published: true, blockers: [] });
  api.mockImplementation(
    async (path: string, method?: string, body?: Record<string, unknown>) => {
      if (!method) return structuredClone(state);
      if (path === "/seasons") state.seasons = [nov, dec];
      if (path === "/member-season")
        state.member_season = {
          season_id: Number(body?.season_id),
          revision: 4,
        };
      if (path === "/seasons/4")
        state.seasons = state.seasons.map((s) =>
          s.id === 4 ? { ...s, status: "archived" } : s,
        );
      return {};
    },
  );
});
const writes = () =>
  api.mock.calls.filter((c) => c[1]).map((c) => `${c[1]} ${c[0]}`);
it.each([true, false])(
  "Start creates, shows, optionally opens, and locks previous month LAST (%s)",
  async (open) => {
    await finishMonth("2026-12", open, seen);
    expect(writes()).toEqual([
      "POST /seasons",
      "PUT /member-season",
      ...(open ? ["PATCH /seasons/5"] : []),
      "PATCH /seasons/4",
    ]);
    expect(api).toHaveBeenLastCalledWith("/seasons/4", "PATCH", {
      status: "archived",
    });
  },
);
it("a retry skips create/show/open already completed and only locks old month", async () => {
  state = {
    seasons: [nov, { ...dec, signup_open: true }],
    member_season: { season_id: 5, revision: 4 },
  };
  await finishMonth("2026-12", true, seen);
  expect(writes()).toEqual(["PATCH /seasons/4"]);
});
it("unfinished results block before every write", async () => {
  readiness.mockResolvedValue({
    published: true,
    blockers: ["Fixture clan: bonuses"],
  });
  await expect(finishMonth("2026-12", false, seen)).rejects.toThrow(
    "Finish these first",
  );
  expect(writes()).toEqual([]);
});
it("stale member season stops without writing", async () => {
  state.member_season = { season_id: 99, revision: 9 };
  await expect(finishMonth("2026-12", true, seen)).rejects.toThrow(
    "Changed by someone else",
  );
  expect(writes()).toEqual([]);
});
it("failure names done/not done including lock; no implicit retry", async () => {
  const original = api.getMockImplementation()!;
  api.mockImplementation(async (...args) => {
    if (args[0] === "/seasons/5") throw new Error("Open failed");
    return original(...args);
  });
  await expect(finishMonth("2026-12", true, seen)).rejects.toThrow(
    "Done: create December 2026, show December 2026 to members. Not done: open December 2026 signups, lock the previous month.",
  );
  expect(writes().filter((s) => s === "PATCH /seasons/4")).toHaveLength(0);
});
it("member change after show prevents archive", async () => {
  const original = api.getMockImplementation()!;
  let reads = 0;
  api.mockImplementation(async (...args) => {
    const value = await original(...args);
    if (args[0] === "/seasons" && !args[1] && ++reads === 3)
      return { ...state, member_season: { season_id: 99, revision: 9 } };
    return value;
  });
  await expect(finishMonth("2026-12", false, seen)).rejects.toThrow(
    "Done: create December 2026, show December 2026 to members. Not done: lock the previous month.",
  );
  expect(writes()).not.toContain("PATCH /seasons/4");
});
