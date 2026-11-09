import { expect, it } from "vitest";
import { activityPages, groupRows } from "./strikeActivityGroups";
import type { ActivityAccount } from "./strikeActivityView";
const account = (n: number, extra: Partial<ActivityAccount>): ActivityAccount =>
  ({
    player_tag: `#P${n}`,
    player_name: `Account ${n}`,
    active_strikes: 0,
    total_strikes: 0,
    ...extra,
  }) as ActivityAccount;
it("never splits a Discord group across pages and puts unlinked accounts last", () => {
  const rows = [
    ...Array.from({ length: 20 }, (_, i) =>
      account(i, { discord_id: "100000000000000001", discord_name: "Slayer" }),
    ),
    ...Array.from({ length: 10 }, (_, i) =>
      account(100 + i, {
        discord_id: "100000000000000002",
        discord_name: "Ace",
      }),
    ),
    account(200, {}),
  ];
  const pages = activityPages(rows, "discord");
  // Ace (10) fits; Slayer (20) would make 30, so it starts page two; the unlinked account fits after it.
  expect(pages.map((page) => page.length)).toEqual([10, 21]);
  expect(pages[0].every((row) => row.discord_name === "Ace")).toBe(true);
  expect(pages[1].filter((row) => row.discord_name === "Slayer")).toHaveLength(
    20,
  );
  const heads = groupRows(rows, "discord").map((group) => group.head.label);
  expect(heads).toEqual(["Ace", "Slayer", "No linked member"]);
});
it("gives one group larger than a page its own page", () => {
  const rows = Array.from({ length: 46 }, (_, i) =>
    account(i, { discord_id: "100000000000000001", discord_name: "Slayer" }),
  );
  expect(activityPages(rows, "discord").map((page) => page.length)).toEqual([
    46,
  ]);
  expect(activityPages(rows, "none").map((page) => page.length)).toEqual([
    25, 21,
  ]);
});
