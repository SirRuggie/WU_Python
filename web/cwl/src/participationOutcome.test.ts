import { describe, expect, it } from "vitest";
import {
  countText,
  matchesOutcome,
  outcomeCounts,
  outcomeLabels,
  outcomeTone,
  participationOutcome,
} from "./participationOutcome";

const lazy = (
  attacks: number | null,
  stars: number | null,
  complete = true,
) => ({
  pool: "lazy" as const,
  attacks,
  stars,
  source_complete: complete,
});
const main = (attacks: number | null, complete = true) => ({
  pool: "main" as const,
  attacks,
  stars: attacks === null ? null : 0,
  source_complete: complete,
});

describe("participation outcome", () => {
  it("applies the Lazy rule: 4 attacks, or 3 attacks and 8 stars", () => {
    expect(participationOutcome(lazy(4, 0), null)).toBe("meets");
    expect(participationOutcome(lazy(7, 21), null)).toBe("meets");
    expect(participationOutcome(lazy(3, 8), null)).toBe("meets");
    expect(participationOutcome(lazy(3, 7), null)).toBe("below");
    expect(participationOutcome(lazy(2, 6), null)).toBe("below");
  });
  it("is Not checked only when nothing was captured", () => {
    expect(participationOutcome(lazy(null, null), null)).toBe("not_checked");
    expect(participationOutcome(lazy(null, null, false), null)).toBe(
      "not_checked",
    );
    expect(participationOutcome(main(null, false), 3)).toBe("not_checked");
  });
  it("is Partial results when some numbers exist but results are incomplete", () => {
    expect(participationOutcome(lazy(5, 12, false), null)).toBe("partial");
    expect(participationOutcome(lazy(3, null), null)).toBe("partial");
    expect(participationOutcome(lazy(null, 4, false), null)).toBe("partial");
    expect(participationOutcome(main(2, false), 3)).toBe("partial");
    expect(outcomeLabels.partial).toBe("Partial results");
    expect(outcomeLabels.not_checked).toBe("Not checked");
  });
  it("uses the saved Main minimum and gives no outcome without one", () => {
    expect(participationOutcome(main(3), 3)).toBe("meets");
    expect(participationOutcome(main(2), 3)).toBe("below");
    expect(participationOutcome(main(0), 0)).toBe("meets");
    expect(participationOutcome(main(7), null)).toBeNull();
    expect(participationOutcome(main(null), undefined)).toBeNull();
  });
  it("maps each outcome to one tone", () => {
    expect(outcomeTone("meets")).toBe("success");
    expect(outcomeTone("below")).toBe("danger");
    expect(outcomeTone("not_checked")).toBe("warning");
    expect(outcomeTone("partial")).toBe("warning");
  });
  it("counts and filters by outcome", () => {
    const rows = [
      lazy(4, 0),
      lazy(3, 7),
      lazy(null, null),
      lazy(3, 9),
      lazy(2, 4, false),
    ];
    expect(outcomeCounts(rows, null)).toEqual({
      all: 5,
      meets: 2,
      below: 1,
      partial: 1,
      not_checked: 1,
    });
    expect(rows.filter((row) => matchesOutcome(row, "below", null))).toEqual([
      rows[1],
    ]);
    expect(rows.filter((row) => matchesOutcome(row, "all", null))).toHaveLength(
      5,
    );
    expect(rows.filter((row) => matchesOutcome(row, "partial", null))).toEqual([
      rows[4],
    ]);
  });
  it("uses singular grammar for one", () => {
    expect(countText(1, "attack")).toBe("1 attack");
    expect(countText(2, "attack")).toBe("2 attacks");
    expect(countText(0, "player")).toBe("0 players");
  });
});
