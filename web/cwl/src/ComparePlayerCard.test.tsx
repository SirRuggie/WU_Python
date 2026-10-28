// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import ComparePlayerCard from "./ComparePlayerCard";
import type { RosterAccount, RosterClan } from "./roster";
import type { ComparisonLocation } from "./comparisonLocation";
const account = {
  tag: "#P2Y",
  player_name: "Aurora",
  town_hall: 18,
  kept: true,
  assigned_clan_tag: "#A",
  effective_weight: 170000,
} as RosterAccount;
const clan = {
  tag: "#A",
  min_weight: 150000,
  max_weight: 170000,
} as RosterClan;
const now = Date.parse("2026-10-27T12:02:00Z");
const record = {
  current_clan_tag: "#B",
  current_clan_name: "Other clan",
  current_clan_checked_at: "2026-10-27T12:00:00Z",
  outside_family: true,
} as ComparisonLocation;
function card(
  location: ComparisonLocation | undefined = record,
  published: [] | null = null,
  weight: number | null = 170000,
) {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <ComparePlayerCard
      account={{ ...account, effective_weight: weight }}
      clan={clan}
      record={location}
      now={now}
      published={published}
      busy={false}
      onDetails={() => {}}
    />,
  );
  return host.querySelector<HTMLButtonElement>(".compare-player-body")!;
}
it("has four rows in order with the TH icon beside TH, a separate Now in row and complete accessible description", () => {
  const body = card();
  expect([...body.children].map((row) => row.className)).toEqual([
    "compare-player-top",
    "compare-player-meta",
    "compare-player-location",
    "compare-player-tags",
  ]);
  expect(body.children[0].querySelector(".town-hall-icon")).toBeNull();
  expect(
    body.children[1].querySelector(".town-hall-icon")?.getAttribute("alt"),
  ).toBe("Town Hall 18");
  expect(body.children[1].textContent).toContain("TH 18 · #P2Y");
  expect(body.children[2].textContent).toContain("Now in Other clan, 2m ago");
  expect(body.children[2].querySelector(".compare-location-pill")).toBeNull();
  expect(body.children[3].textContent).toBe(
    "Not in this clan, Outside weight range, Outside family",
  );
  const ids = body.getAttribute("aria-describedby")!.split(" ");
  expect(
    ids
      .map(
        (id) =>
          [...body.querySelectorAll("[id]")].find(
            (element) => element.id === id,
          )?.textContent,
      )
      .join(" "),
  ).toContain("170k TH 18 · #P2Y");
});
it("checking has its own row with no age; No clan retains age", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <ComparePlayerCard
      account={account}
      clan={clan}
      now={now}
      published={null}
      busy={false}
      onDetails={() => {}}
    />,
  );
  expect(host.querySelector(".compare-player-location")?.textContent).toBe(
    "Checking location…",
  );
  expect(host.querySelector(".compare-location-age")).toBeNull();
  expect(host.querySelector(".compare-player-tags")?.textContent).toContain(
    "Checking…",
  );
  expect(
    card({ ...record, current_clan_tag: null, current_clan_name: null })
      .children[2].textContent,
  ).toBe("No clan, 2m ago");
  expect(host.querySelector(".compare-player-body")?.children).toHaveLength(4);
});
it("a publication note adds exactly one fifth row and missing weight replaces the headline number", () => {
  const body = card(record, [], null);
  expect(body.children).toHaveLength(5);
  expect(body.children[4].className).toBe("compare-publish-note");
  expect(body.children[4].textContent).toBe("Not published yet");
  expect(body.children[0].querySelector(".is-danger")?.textContent).toBe(
    "No weight",
  );
  expect(body.children[3].textContent).not.toContain("No weight");
});
