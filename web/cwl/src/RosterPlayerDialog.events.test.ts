import { describe, expect, it } from "vitest";
import { dialogOwnsEvent } from "./RosterPlayerDialog";

describe("player dialog portal keyboard isolation", () => {
  const outerControl = {} as EventTarget;
  const menuControl = {} as EventTarget;
  const outerDialog = {
    contains: (target: Node) => target === outerControl,
  } as Pick<HTMLDialogElement, "contains">;

  it("allows Tab trapping only for targets in the player dialog", () => {
    expect(dialogOwnsEvent(outerDialog, outerControl)).toBe(true);
    expect(dialogOwnsEvent(outerDialog, menuControl)).toBe(false);
  });

  it("ignores events when the player dialog is absent", () => {
    expect(dialogOwnsEvent(null, outerControl)).toBe(false);
    expect(dialogOwnsEvent(outerDialog, null)).toBe(false);
  });
});
