import { expect, it } from "vitest";
import { declarationSnapshot, type DeclarationData } from "./declarationData";
it("Details uses published weights/locks/placements rather than current draft values", () => {
  const result = declarationSnapshot({
    arrival: {
      accounts: [
        {
          tag: "#P",
          assigned_clan_tag: "#OLD",
          assigned_clan_name: "Old name",
          current_clan_tag: "#HERE",
          current_clan_name: "Here",
        },
      ],
    },
    roster: {
      revision: 4,
      accounts: [{ tag: "#P", manual_weight: 999, assigned_clan_tag: "#NEW" }],
      clans: [{ tag: "#OLD", name: "Renamed" }],
    },
    publishedAccounts: [
      {
        tag: "#P",
        manual_weight: 170000,
        effective_weight: 170000,
        kept: true,
        assigned_clan_tag: "#OLD",
      },
    ],
  } as unknown as DeclarationData);
  expect(result.accounts[0]).toMatchObject({
    manual_weight: 170000,
    kept: true,
    assigned_clan_tag: "#OLD",
    current_clan_tag: "#HERE",
  });
  expect(result.clans[0].name).toBe("Old name");
  expect(result.undo).toBeNull();
});
