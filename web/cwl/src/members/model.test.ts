import { expect, it } from "vitest";
import {
  emptyFilters,
  filterMembers,
  statusCounts,
  localMemberTime,
  matchesMember,
  sortMembers,
  type DirectoryMember,
} from "./model";
const make = (i: number): DirectoryMember => ({
  discord_id: String(100000000000000000n + BigInt(i)),
  name: `Person ${i}`,
  nickname: `Nick ${i}`,
  username: `user${i}`,
  bot: i < 3,
  status: "Missing",
  profile: null,
  parsed: null,
  skip_reason: null,
  role_ids: i % 2 ? ["role-a"] : [],
});
const rows = Array.from({ length: 1448 }, (_, i) => make(i));
it("1448 fixture defaults hide bots and status counts use the same combined filters", () => {
  expect(filterMembers(rows, emptyFilters, new Set()).length).toBe(1445);
  expect(statusCounts(rows, emptyFilters, new Set())).toEqual({
    all: 1445,
    needs_flag: 1445,
    no_time_zone: 1445,
    check_name: 0,
  });
});
it("combines search with roles, supports No role and OR across role choices", () => {
  const filters = { ...emptyFilters, query: "Person 10", roles: ["role-a"] };
  const result = filterMembers(rows, filters, new Set());
  expect(
    result.every(
      (row) =>
        row.name.includes("Person 10") && row.role_ids.includes("role-a"),
    ),
  ).toBe(true);
  expect(result.length).toBeGreaterThan(0);
  const none = filterMembers(
    rows,
    { ...emptyFilters, roles: ["none"] },
    new Set(),
  );
  expect(none.every((row) => !row.role_ids.length)).toBe(true);
  expect(
    filterMembers(
      rows,
      { ...emptyFilters, roles: ["none", "role-a"] },
      new Set(),
    ).length,
  ).toBe(1445);
});
it("searches nickname, username, ID and normalized text", () => {
  const row = make(42);
  row.name = "Ｆｕｌｌ width";
  expect(matchesMember(row, "full")).toBe(true);
  for (const query of ["Nick 42", "user42", row.discord_id])
    expect(matchesMember(row, query)).toBe(true);
});
it("shows hidden selected people without changing the selection", () => {
  const selected = new Set([rows[123].discord_id]);
  expect(
    filterMembers(rows, { ...emptyFilters, selectedOnly: true }, selected).map(
      (r) => r.discord_id,
    ),
  ).toEqual([...selected]);
  expect(selected.size).toBe(1);
});
it("keeps zero-offset zones valid and formats the time at their stored offset", () => {
  const row = make(5);
  row.parsed = { label: "GMT", offsetMinutes: 0 };
  expect(
    filterMembers(
      [row],
      { ...emptyFilters, status: "no_time_zone" },
      new Set(),
    ),
  ).toHaveLength(0);
  expect(localMemberTime(row, new Date("2026-11-01T08:12:00Z"))).toContain(
    "8:12",
  );
});

it("time zone sort puts unknown last, keeps name ties stable and does not mutate the input", () => {
  const west = { ...make(2), parsed: { label: "GMT-8", offsetMinutes: -480 } },
    east = { ...make(1), parsed: { label: "GMT+1", offsetMinutes: 60 } },
    unknown = make(0);
  const input = [unknown, east, west];
  expect(sortMembers(input, "time_zone").map((row) => row.discord_id)).toEqual([
    west.discord_id,
    east.discord_id,
    unknown.discord_id,
  ]);
  expect(input).toEqual([unknown, east, west]);
  expect(
    sortMembers([make(10), make(2)], "name").map((row) => row.name),
  ).toEqual(["Person 2", "Person 10"]);
});
