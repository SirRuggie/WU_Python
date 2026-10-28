// @vitest-environment happy-dom
import { Window } from "happy-dom";
import { readFileSync } from "node:fs";
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
  name: "Assigned clan",
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
function describedText(element: Element) {
  const copy = element.cloneNode(true) as Element;
  copy
    .querySelectorAll('[aria-hidden="true"]')
    .forEach((node) => node.remove());
  return copy.textContent;
}
function visibleText(element: Element) {
  const copy = element.cloneNode(true) as Element;
  copy.querySelectorAll(".sr-only").forEach((node) => node.remove());
  return copy.textContent;
}
it("shows a dot before the age but describes a comma for clan and no-clan locations", () => {
  for (const [location, label] of [
    [record, "Other clan"],
    [
      { ...record, current_clan_tag: null, current_clan_name: null },
      "in no clan",
    ],
  ] as const) {
    const row = card(location).children[2];
    expect(visibleText(row)).toBe(`Assigned clan→ ${label} · 2m ago`);
    expect(describedText(row)).toBe(
      `Assigned clan: Assigned clan. Now in ${label === "in no clan" ? "no clan" : label}, checked 2 minutes ago.`,
    );
  }
});
it("has four rows in order with the TH icon before the name, a separate Now in row and complete accessible description", () => {
  const body = card();
  expect([...body.children].map((row) => row.className)).toEqual([
    "player-card-top compare-player-top",
    "player-card-meta compare-player-meta",
    "player-clan-status compare-player-location",
    "compare-player-tags",
  ]);
  expect(body.children[1].querySelector(".town-hall-icon")).toBeNull();
  expect(
    body.children[0].firstElementChild?.querySelector(".town-hall-icon"),
  ).not.toBeNull();
  expect(
    body.children[1].querySelector('[aria-label="Locked placement"]'),
  ).not.toBeNull();
  expect(
    body.children[0].querySelector(".town-hall-icon")?.getAttribute("alt"),
  ).toBe("Town Hall 18");
  expect(body.children[1].textContent).toContain("TH 18 · #P2Y");
  expect(describedText(body.children[2])).toBe(
    "Assigned clan: Assigned clan. Now in Other clan, checked 2 minutes ago.",
  );
  expect(body.children[2].querySelector(".compare-location-pill")).toBeNull();
  expect(body.children[3].textContent).toBe(
    ", Outside weight range, Outside family",
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
  expect(visibleText(host.querySelector(".compare-player-location")!)).toBe(
    "Assigned clan· Checking…",
  );
  expect(host.querySelector(".compare-location-age")).toBeNull();
  expect(host.querySelector(".compare-player-tags")?.textContent).not.toContain(
    "Checking…",
  );
  expect(
    describedText(
      card({ ...record, current_clan_tag: null, current_clan_name: null })
        .children[2],
    ),
  ).toBe(
    "Assigned clan: Assigned clan. Now in no clan, checked 2 minutes ago.",
  );
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

it.each([360, 700, 1440])(
  "Compare stays compact at %ipx and colors an elsewhere clan red",
  (width) => {
    const body = card();
    const w = new Window({ width });
    w.document.head.innerHTML = `<style>${readFileSync("src/rosterUi/tokens.css", "utf8")}${readFileSync("src/PlayerCard.css", "utf8")}</style>`;
    w.document.body.innerHTML = `<main class="roster-ui">${body.parentElement!.outerHTML}</main>`;
    const article = w.document.querySelector("article")!;
    expect(article.classList.contains("player-card-compact")).toBe(true);
    expect(
      w.getComputedStyle(article.querySelector(".town-hall-icon")!).width,
    ).toBe("40px");
    expect(
      w.getComputedStyle(article.querySelector(".player-card-body")!)
        .paddingTop,
    ).toBe("3px");
    expect(
      w.getComputedStyle(article.querySelector(".player-card-weight")!)
        .fontSize,
    ).toBe("16px");
    expect(
      w.getComputedStyle(article.querySelector(".player-current-clan")!).color,
    ).toBe("#ffdbde");
    expect(
      w.getComputedStyle(article.querySelector(".player-clan-status")!)
        .paddingRight,
    ).toBe("40px");
    w.happyDOM.abort();
  },
);

it("puts In clan inline and omits the chip row entirely when there are no warnings", () => {
  const body = card(
    {
      ...record,
      current_clan_tag: "#A",
      current_clan_name: "Assigned clan",
      outside_family: false,
    },
    null,
    160000,
  );
  expect(visibleText(body.children[2])).toBe("Assigned clanIn clan· 2m ago");
  expect(body.querySelector(".player-in-clan-pill")?.textContent).toBe(
    "In clan",
  );
  expect(body.querySelector(".compare-player-tags")).toBeNull();
  expect(body.querySelector(".compare-location-pill")).toBeNull();
  expect(body.children).toHaveLength(3);
});
