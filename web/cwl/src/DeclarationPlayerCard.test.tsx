import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import DeclarationPlayerCard from "./DeclarationPlayerCard";
import type { RosterAccount } from "./roster";

it("uses the shared Now in pin for declaration locations", () => {
  const account = {
    tag: "#PLAYER",
    player_name: "Amber",
    pool: "main",
    assigned_clan_tag: "#HOME",
    town_hall: 18,
    effective_weight: 120000,
  } as RosterAccount;
  const html = renderToStaticMarkup(
    <DeclarationPlayerCard
      account={account}
      clanName="Home"
      record={{
        current_clan_tag: "#OTHER",
        current_clan_name: "Other clan",
        current_clan_checked_at: "2026-10-28T12:00:00Z",
      }}
      now={Date.parse("2026-10-28T12:04:00Z")}
      request={{ seasonId: "1" }}
    />,
  );
  expect(html).toContain(
    'class="lucide lucide-map-pin player-location-pin" aria-hidden="true"',
  );
  expect(html).not.toContain("→");
});
