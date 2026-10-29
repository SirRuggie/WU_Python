import { afterEach, describe, it, expect, vi } from "vitest";
import {
  activeRosterActionMenu,
  setRosterActionMenu,
  subscribeRosterActionMenus,
  closeRosterActionMenus,
} from "./actionMenuState";
afterEach(closeRosterActionMenus);
describe("shared roster action menu ownership", () => {
  it("opening a second closes the first and notifies mounted menus", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeRosterActionMenus(listener);
    setRosterActionMenu("first");
    expect(activeRosterActionMenu()).toBe("first");
    setRosterActionMenu("second");
    expect(activeRosterActionMenu()).toBe("second");
    expect(listener).toHaveBeenCalledTimes(2);
    closeRosterActionMenus();
    expect(activeRosterActionMenu()).toBeNull();
    unsubscribe();
  });
});
