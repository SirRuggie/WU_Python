// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { clanCapacity } from "./rosterCapacity";
import { readinessAccounts } from "./readiness";
import { capacityWarnings } from "./publicationStatus";
import CompareClanHeader from "./CompareClanHeader";
import ClanSettings from "./ClanSettings";
import RosterClanChips from "./RosterClanChips";
import type { RosterAccount, RosterClan } from "./roster";
import type { PublicationDraft } from "./publication";
for (const cap of [15, 30])
  for (const filler of [false, true])
    it(`all capacity displays share ${cap} +1 ${filler ? "filler" : "regular"} classification`, () => {
      const accounts = Array.from({ length: cap + 1 }, (_, i) => ({
        tag: String(i),
        assigned_clan_tag: "#HOST",
        player_name: "Member",
        effective_weight: 100000,
        town_hall: 16,
        roster_filler: filler && i === 0,
        pool: "lazy",
      })) as RosterAccount[];
      const clan = {
        tag: "#HOST",
        name: "Host",
        pool: "lazy",
        capacity: cap,
        effective_capacity: cap,
        assigned_count: cap + 1,
        assigned_filler_count: Number(filler),
        archived: false,
        min_weight: null,
        max_weight: null,
      } as RosterClan;
      expect(clanCapacity(accounts, clan.tag, cap).over).toBe(!filler);
      expect(readinessAccounts(accounts, [clan], "over_capacity")).toHaveLength(
        filler ? 0 : cap + 1,
      );
      expect(
        capacityWarnings({
          preview: { accounts, clans: [clan] },
        } as PublicationDraft).clans,
      ).toBe(filler ? 0 : 1);
      const views = [
        <CompareClanHeader clan={clan} accounts={accounts} locations={{}} />,
        <RosterClanChips
          roster={{ revision: 1, undo: null, accounts, clans: [clan] }}
          pool="lazy"
          selectedTags={[]}
          onSelect={() => {}}
          disabled={false}
        />,
        <ClanSettings
          clans={[clan]}
          accounts={accounts}
          pool="lazy"
          busy={false}
          archived={false}
          onPoolChange={() => {}}
          onDirty={() => {}}
          onLeave={() => true}
          onSave={async () => true}
        />,
      ];
      for (const view of views) {
        const host = document.createElement("div");
        host.innerHTML = renderToStaticMarkup(view);
        expect(!!host.querySelector(".is-over")).toBe(!filler);
        if (filler) expect(host.querySelector(".is-full")).toBeNull();
        if (filler) expect(host.textContent).toContain("+1 filler");
      }
      const host = document.createElement("div");
      host.innerHTML = renderToStaticMarkup(views[1]);
      if (filler)
        expect(
          host.querySelector(".roster-clan-chip-count")?.textContent,
        ).toContain("+1 filler");
    });

it("regular capacity alone stays full while filler-only overflow uses room styling", () => {
  expect(
    clanCapacity(
      Array.from({ length: 15 }, () => ({
        assigned_clan_tag: "A",
      })) as RosterAccount[],
      "A",
      15,
    ).barClass,
  ).toBe("is-full");
});
