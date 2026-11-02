import { expect, it } from "vitest";
import { patchDeclarationMark } from "./declarationMarks";
import type { DeclarationExtraResponse } from "./declarationExtras";
it("patches only membership classifications and revision, preserving observations for successive marks and Undo", () => {
  let data = {
    source: "published",
    basis: 3,
    revision: 1,
    clans: [
      {
        tag: "#A",
        name: "A",
        capacity: 15,
        status: "current",
        checked_at: "2026-11-01T00:00:00Z",
        count: 5,
        extras: Array.from({ length: 5 }, (_, i) => ({
          tag: String(i),
          name: String(i),
          town_hall: 16,
          context: "Not signed up",
          assigned_clan_tag: null,
          assigned_here: false,
        })),
        low_th: [],
        fillers: [],
      },
      {
        tag: "#B",
        name: "B",
        capacity: 15,
        status: "unavailable",
        checked_at: null,
        count: null,
        extras: null,
      },
    ],
  } as DeclarationExtraResponse;
  const other = data.clans[1];
  for (let i = 0; i < 5; i++)
    data = patchDeclarationMark(data, {
      tag: String(i),
      revision: i + 2,
      roster_filler: true,
      mark_revision: 1,
    });
  expect(data.clans[0].count).toBe(0);
  expect(data.clans[0].fillers).toHaveLength(5);
  expect(data.clans[1]).toBe(other);
  expect(data.clans[0].checked_at).toBe("2026-11-01T00:00:00Z");
  data = patchDeclarationMark(data, {
    tag: "0",
    revision: 7,
    roster_filler: false,
    mark_revision: 2,
  });
  expect(data.clans[0].count).toBe(1);
  expect(data.clans[0].extras?.[0].tag).toBe("0");
  expect(data.clans[0].extras?.[0].roster_filler_revision).toBe(2);
  expect(data.basis).toBe(3);
});
it("keeps draft-moved accounts neutral through a filler tick and Undo", () => {
  const member = {
    tag: "#P",
    name: "Moved",
    town_hall: 16,
    context: "Assigned to A",
    assigned_clan_tag: "#A",
    assigned_here: false,
    not_published_yet: true,
    roster_filler: false,
  };
  let data = {
    source: "published",
    basis: 1,
    revision: 2,
    clans: [
      {
        tag: "#A",
        name: "A",
        capacity: 15,
        status: "current",
        checked_at: "2026-11-01",
        count: 0,
        extras: [],
        unpublished: [member],
        unpublished_count: 1,
        low_th: [],
        fillers: [],
      },
    ],
  } as DeclarationExtraResponse;
  for (const value of [true, false]) {
    data = patchDeclarationMark(data, {
      tag: "#P",
      roster_filler: value,
      mark_revision: 1,
      revision: 3,
    });
    expect(data.clans[0].count).toBe(0);
    expect(data.clans[0].extras).toHaveLength(0);
    expect(data.clans[0].unpublished_count).toBe(1);
    expect(data.clans[0].unpublished?.[0].roster_filler).toBe(value);
    expect(data.basis).toBe(1);
  }
});
