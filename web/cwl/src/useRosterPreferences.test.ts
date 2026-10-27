import { describe, expect, it } from "vitest";
import {
  readRosterPreferences,
  saveRosterPreferences,
  ROSTER_ORDER_KEY,
} from "./useRosterPreferences";
import { DEFAULT_ROSTER_RELEASE_PREFERENCES as defaults } from "./rosterReleaseModel";
const store = () => {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
  };
};
describe("roster device order persistence", () => {
  it("persists only sort/group across seasons; keeps filters season scoped", () => {
    const session = store(),
      local = store();
    saveRosterPreferences(
      "season1",
      {
        ...defaults,
        search: "Alice",
        pool: "lazy",
        sort: "weight_asc",
        grouped: true,
      },
      () => session,
      () => local,
    );
    expect(JSON.parse(local.getItem(ROSTER_ORDER_KEY)!)).toEqual({
      sort: "weight_asc",
      grouped: true,
    });
    expect(
      readRosterPreferences(
        "season1",
        () => session,
        () => local,
      ),
    ).toMatchObject({
      search: "Alice",
      pool: "lazy",
      sort: "weight_asc",
      grouped: true,
    });
    expect(
      readRosterPreferences(
        "season2",
        () => session,
        () => local,
      ),
    ).toMatchObject({
      search: "",
      pool: "all",
      sort: "weight_asc",
      grouped: true,
    });
  });
  it("rejects corrupt JSON/unknown values and survives denied storage access", () => {
    const session = store(),
      local = store();
    session.setItem("s", "null");
    local.setItem(ROSTER_ORDER_KEY, "{broken");
    expect(
      readRosterPreferences(
        "s",
        () => session,
        () => local,
      ),
    ).toEqual(defaults);
    local.setItem(
      ROSTER_ORDER_KEY,
      JSON.stringify({ sort: "attack", grouped: "yes" }),
    );
    expect(
      readRosterPreferences(
        "s",
        () => session,
        () => local,
      ),
    ).toEqual(defaults);
    const denied = () => {
      throw new Error("blocked");
    };
    expect(readRosterPreferences("s", denied, denied)).toEqual(defaults);
    expect(
      saveRosterPreferences("s", { ...defaults, sort: "name" }, denied, denied)
        .sort,
    ).toBe("name");
  });
});
