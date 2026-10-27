import { describe, expect, it, vi } from "vitest";
import { commitRosterMenuAction, type RosterMenuOption } from "./Menu";

const options: RosterMenuOption[] = [
  { value: "main", label: "Main CWL" },
  { value: "lazy", label: "Lazy CWL", disabled: true },
];

describe("RosterMenu action semantics", () => {
  it("changes a value only when an enabled item is activated", () => {
    const change = vi.fn();
    expect(commitRosterMenuAction("main", options, change)).toBe(true);
    expect(change).toHaveBeenCalledWith("main");
  });

  it("ignores disabled and unknown actions", () => {
    const change = vi.fn();
    expect(commitRosterMenuAction("lazy", options, change)).toBe(false);
    expect(commitRosterMenuAction("other", options, change)).toBe(false);
    expect(change).not.toHaveBeenCalled();
  });
});
