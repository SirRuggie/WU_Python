import { expect, it } from "vitest";
import type { GameResult } from "./dashboardSearch";
import type { Account, Clan } from "./api";
import {
  familyGameResults,
  mergeGameResults,
  gameTag,
} from "./dashboardSearch";
it("matches47loaded family accounts without a provider or another user's cache", () => {
  const accounts = Array.from(
    { length: 47 },
    (_, i) =>
      ({
        tag: `#P2Y${i}`,
        name: `Fixture ${i}`,
        current_clan_tag: null,
        current_clan_name: null,
        town_hall: 18,
      }) as Account,
  );
  const left = familyGameResults(accounts, [], "fixture"),
    right = familyGameResults([], [], "fixture");
  expect(left).toHaveLength(47);
  expect(right).toEqual([]);
  expect(
    mergeGameResults(left, [
      {
        kind: "player",
        tag: accounts[0].tag,
        name: "Public duplicate",
        source: "clash",
      },
    ]),
  ).toHaveLength(47);
  expect(gameTag(" poy ")).toBe("#P0Y");
  expect(gameTag("#" + "P".repeat(13))).toBeNull();
});
it("does not grant a family directory unless authorized data was supplied", () => {
  const clan = { tag: "#R2Y", name: "Fixture family" } as Clan;
  expect(familyGameResults([], [], "family")).toEqual([]);
  expect(familyGameResults([], [clan], "family")[0].source).toBe("family");
});

it("whitelists local family fields and ignores untrusted family flags from the public response", () => {
  const accounts = [
    {
      tag: "#P2Y",
      name: "Fixture",
      town_hall: 18,
      current_clan_tag: null,
      current_clan_name: null,
      discord_id: "PRIVATE",
    } as unknown as Account,
  ];
  const family = familyGameResults(accounts, [], "fixture");
  expect(JSON.stringify(family)).not.toContain("PRIVATE");
  const publicRows = [
    { kind: "clan", tag: "#C2Y", name: "Clash", source: "clash" },
    { kind: "player", tag: "#Q2Y", name: "Forged", source: "family" },
  ] as GameResult[];
  expect(mergeGameResults(family, publicRows).map((row) => row.name)).toEqual([
    "Fixture",
    "Clash",
  ]);
});
