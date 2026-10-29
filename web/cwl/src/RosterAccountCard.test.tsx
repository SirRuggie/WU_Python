// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { Window } from "happy-dom";
import { readFileSync } from "node:fs";
const cardCss = readFileSync("src/PlayerCard.css", "utf8");
const accountCss = readFileSync("src/RosterAccountCard.css", "utf8");
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RosterAccount } from "./roster";
import RosterAccountCard from "./RosterAccountCard";

afterEach(() => vi.restoreAllMocks());

const account: RosterAccount = {
  tag: "#PLAYER",
  user_id: "123",
  pool: "main",
  player_name: "<Alpha & Beta>",
  town_hall: null,
  prefer_crystal_1_or_lower: false,
  source_weight: null,
  source_status: "missing",
  source_name: null,
  source_checked_at: null,
  source_modified_at: null,
  manual_weight: null,
  effective_weight: null,
  assigned_clan_tag: null,
  kept: true,
  current_clan_status: "unavailable",
};

function render(
  overrides: Partial<Parameters<typeof RosterAccountCard>[0]> = {},
) {
  return renderToStaticMarkup(
    <RosterAccountCard
      now={Date.now()}
      account={account}
      assignedClanName="Unassigned"
      showPool
      selected={false}
      selectionMode
      disabled={false}
      canRoster
      canSignups
      archived={false}
      onToggle={() => {}}
      onDetails={() => {}}
      onAssign={() => {}}
      onSignup={() => {}}
      {...overrides}
    />,
  );
}

describe("roster account card", () => {
  it("shares the TH-first headline and keeps the lock in both responsive layouts", () => {
    const host = document.createElement("div");
    host.innerHTML = render({ account: { ...account, town_hall: 18 } });
    const headline = host.querySelector(".player-card-top")!;
    expect(
      headline.firstElementChild?.querySelector(".town-hall-icon"),
    ).not.toBeNull();
    expect(headline.querySelector(".player-card-name-text")?.textContent).toBe(
      account.player_name,
    );
    expect(
      headline
        .querySelector(".player-card-name")
        ?.firstElementChild?.querySelector(".town-hall-icon"),
    ).not.toBeNull();
    expect(
      host.querySelectorAll('[aria-label="Locked placement"]'),
    ).toHaveLength(2);
    expect(
      host.querySelector('.player-card-meta [aria-label="Locked placement"]'),
    ).not.toBeNull();
    expect(
      host.querySelector(".roster-player-placement")?.textContent,
    ).toContain("Not assigned· location not checked yet");
    host.innerHTML = render({
      account: {
        ...account,
        assigned_clan_tag: "#CLAN",
        current_clan_status: "current",
        current_clan_name: "Home",
        current_clan_checked_at: new Date().toISOString(),
      },
      assignedClanName: "Assigned",
    });
    expect(host.querySelector(".roster-player-placement")?.textContent).toBe(
      "Assigned Home · just now",
    );
  });
  it("escapes player text and presents missing, locked and unavailable values", () => {
    const html = render();
    expect(html).toContain("&lt;Alpha &amp; Beta&gt;");
    expect(html).not.toContain("<Alpha & Beta>");
    expect(html).toContain('aria-label="Select &lt;Alpha &amp; Beta&gt;"');
    expect(html).toContain("No weight");
    expect(html).toContain("Held unassigned");
    expect(html).toContain("location not checked yet");
    expect(html).not.toContain("Unavailable");
    expect(html).toContain("Main CWL");
  });

  it("keeps stale location results with Compare's age formatter", () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-28T14:00:00Z"));
    const html = render({
      account: {
        ...account,
        current_clan_status: "stale",
        current_clan_name: "Old clan",
        current_clan_checked_at: "2026-10-28T12:00:00Z",
      },
    });
    expect(html).toContain("Now in Old clan · 2h 0m ago");
    expect(html).not.toContain("location not checked yet");
    expect(html).toContain(
      'role="note" aria-label="Assigned clan: Not assigned. Now in Old clan',
    );
    expect(html).not.toContain("→");
  });
  it("removes only the capacity note from cards", () => {
    const capacity = render({
      account: {
        ...account,
        kept: false,
        auto_placement_note:
          "Hosting clans need a 15- or 30-player capacity in Clan settings.",
      },
    });
    expect(capacity).not.toContain("Hosting clans need");
    expect(
      render({
        account: {
          ...account,
          kept: false,
          auto_placement_note: "Needs review",
        },
      }),
    ).toContain("Needs review");
  });
  it("omits duplicate Not assigned notes but preserves real notes and Held", () => {
    const host = document.createElement("div");
    host.innerHTML = render({
      account: {
        ...account,
        kept: false,
        auto_placement_reason: "missing_weight",
      },
    });
    expect(host.querySelector(".roster-player-note")).toBeNull();
    expect(host.querySelector(".roster-player-sr-only")?.textContent).toContain(
      "Assigned clan: Not assigned.",
    );
    host.innerHTML = render({
      account: { ...account, kept: false, auto_placement_note: "Needs review" },
    });
    expect(host.querySelector(".roster-player-note")?.textContent).toBe(
      "Needs review",
    );
    expect(render()).toContain("Held unassigned");
  });
  it("keeps the full location in a title and ellipsizes only the current clan", () => {
    const html = render({
      account: {
        ...account,
        current_clan_checked_at: new Date().toISOString(),
        current_clan_name: "ClashofThrones",
      },
    });
    expect(html).toContain('title="Now in ClashofThrones · just now"');
    const style = document.createElement("style");
    style.textContent = cardCss + accountCss;
    const host = document.createElement("div");
    host.className = "roster-ui roster-workspace";
    host.style.width = "300px";
    host.innerHTML = html;
    document.head.append(style);
    document.body.append(host);
    try {
      const row = host.querySelector(".roster-player-placement")!;
      const current = host.querySelector(".roster-player-current")!;
      expect(getComputedStyle(row).display).toBe("flex");
      expect(getComputedStyle(row).whiteSpace).toBe("nowrap");
      expect(getComputedStyle(current).overflow).toBe("hidden");
      expect(getComputedStyle(current).textOverflow).toBe("ellipsis");
      expect(getComputedStyle(row.querySelector("strong")!).flexShrink).toBe(
        "0",
      );
    } finally {
      host.remove();
      style.remove();
    }
  });
  it("keeps card text at least 12px and both compact headline weights 16px bold", () => {
    for (const css of [cardCss, accountCss]) {
      for (const match of css.matchAll(/font-size:\s*(\d+)px/g))
        expect(Number(match[1])).toBeGreaterThanOrEqual(12);
    }
    const css = cardCss;
    expect(css).toMatch(
      /player-card-weight\s*\{[^}]*font-size: 16px;[^}]*font-weight: 700/s,
    );
  });

  it("prevents selection in archived or read-only views while retaining Details", () => {
    const archived = render({ archived: true });
    expect(archived).toMatch(/type="checkbox"[^>]*disabled=""/);
    expect(archived).toContain("Details for &lt;Alpha &amp; Beta&gt;");
    const readOnly = render({ canRoster: false, canSignups: false });
    expect(readOnly).toMatch(/type="checkbox"[^>]*disabled=""/);
    expect(readOnly).toContain("Details for &lt;Alpha &amp; Beta&gt;");
  });
});

it("hides backend ready notes for unassigned, unkept accounts", () => {
  const host = document.createElement("div");
  host.innerHTML = render({
    account: {
      ...account,
      kept: false,
      auto_placement_reason: "ready",
      auto_placement_note:
        "Ready for auto-placement. Preview and apply to assign.",
    },
  });
  expect(host.querySelector(".roster-player-note")).toBeNull();
});
it("says in no clan for a checked clanless account", () => {
  const html = render({
    account: {
      ...account,
      current_clan_checked_at: new Date().toISOString(),
      current_clan_tag: null,
      current_clan_name: null,
    },
  });
  expect(html).toContain("Now in no clan · just now");
  expect(html).not.toContain("now in No clan");
});

it("prioritizes a long assigned name on one line with complete title and accessible location", () => {
  const host = document.createElement("div");
  host.innerHTML = render({
    account: {
      ...account,
      assigned_clan_tag: "#A",
      current_clan_tag: "#B",
      current_clan_name: "Other clan",
      current_clan_checked_at: "2026-10-28T12:00:00Z",
    },
    assignedClanName: "Warriors Unite!",
    now: Date.parse("2026-10-28T12:04:00Z"),
  });
  const row = host.querySelector(".roster-player-placement")!;
  expect(row.getAttribute("title")).toBe(
    "Warriors Unite! Now in Other clan · 4m ago",
  );
  expect(host.querySelector(".roster-player-sr-only")?.textContent).toContain(
    "Assigned clan: Warriors Unite!. Now in Other clan, checked 4 minutes ago.",
  );
  const style = document.createElement("style");
  style.textContent = cardCss + accountCss;
  document.head.append(style);
  document.body.append(host);
  try {
    const name = getComputedStyle(row.querySelector("strong")!);
    expect(name.maxWidth).toBe("100%");
    expect(name.textOverflow).toBe("ellipsis");
    expect(name.flexShrink).toBe("0");
    expect(getComputedStyle(row).whiteSpace).toBe("nowrap");
    expect(
      getComputedStyle(row.querySelector(".roster-player-current")!).minWidth,
    ).toMatch(/^0(px)?$/);
  } finally {
    style.remove();
    host.remove();
  }
});
it.each([
  ["#A", "Home", true, "HomeIn clan· 4m ago", "is-in-clan"],
  ["#B", "Elsewhere", true, "Home Elsewhere · 4m ago", "is-elsewhere"],
  [null, null, false, "Not assigned in no clan · 4m ago", "is-unassigned"],
] as const)(
  "renders the location state %s",
  (tag, name, assigned, text, state) => {
    const host = document.createElement("div");
    host.innerHTML = render({
      account: {
        ...account,
        assigned_clan_tag: assigned ? "#A" : null,
        current_clan_tag: tag,
        current_clan_name: name,
        current_clan_checked_at: "2026-10-28T12:00:00Z",
      },
      assignedClanName: "Home",
      now: Date.parse("2026-10-28T12:04:00Z"),
    });
    const row = host.querySelector(".roster-player-placement")!;
    expect(row.textContent).toBe(text);
    expect(row.classList.contains(state)).toBe(true);
  },
);

it.each([360, 700, 701, 1440])(
  "uses the compact/wide weight and icon layout at %ipx",
  (width) => {
    const w = new Window({ width });
    w.document.head.innerHTML = `<style>${cardCss}${accountCss}</style>`;
    w.document.body.innerHTML = `<main class="roster-ui roster-workspace">${render({ account: { ...account, town_hall: 18, effective_weight: 170000 } })}</main>`;
    const card = w.document.querySelector(".player-card")!;
    expect(card.classList.contains("player-card-responsive")).toBe(true);
    const weight = w.getComputedStyle(
      card.querySelector(".player-card-weight")!,
    );
    expect(weight.fontSize).toBe(width > 700 ? "22px" : "16px");
    expect(weight.gridRow).toBe(width > 700 ? "1 / 4" : "1");
    const icon = w.getComputedStyle(card.querySelector(".town-hall-icon")!);
    expect(icon.width).toBe(width > 700 ? "26px" : "22px");
    expect(
      w.getComputedStyle(card.querySelector(".player-card-meta")!).gridColumn,
    ).toBe(width > 700 ? "1" : "1 / -1");
    expect(
      card.querySelector(".town-hall-icon")?.getAttribute("src"),
    ).toContain("?size=64");
    w.happyDOM.abort();
  },
);

it.each([360, 899, 900, 1440])(
  "shows account columns only at desktop width %ipx",
  (width) => {
    const w = new Window({ width });
    w.document.head.innerHTML = `<style>${cardCss}${accountCss}</style>`;
    w.document.body.innerHTML = `<main class="roster-ui roster-workspace">${render(
      {
        account: {
          ...account,
          town_hall: 18,
          effective_weight: 170000,
          assigned_clan_tag: "#A",
          current_clan_name: "Other clan",
          current_clan_checked_at: "2026-10-28T12:00:00Z",
        },
        assignedClanName: "Assigned clan",
        now: Date.parse("2026-10-28T12:04:00Z"),
      },
    )}</main>`;
    const card = w.document.querySelector(".roster-player-card")!;
    const columns = card.querySelector(".roster-account-columns")!;
    expect(w.getComputedStyle(columns).display).toBe(
      width >= 900 ? "grid" : "none",
    );
    expect(
      w.getComputedStyle(card.querySelector(".player-card-meta")!).display,
    ).toBe(width >= 900 ? "none" : "flex");
    expect([...columns.children].map((column) => column.className)).toEqual([
      "roster-account-column-name",
      "roster-account-column-pool",
      "roster-account-column-assigned",
      "roster-account-column-now",
      "roster-account-column-weight",
    ]);
    expect(
      columns
        .querySelector(".roster-account-column-now .player-location-pin")
        ?.getAttribute("aria-hidden"),
    ).toBe("true");
    expect(
      card.querySelector(".roster-account-column-name")?.textContent,
    ).toContain("#PLAYER · TH18");
    expect(
      card.querySelector(".roster-account-column-assigned")?.textContent,
    ).toBe("Assigned clan");
    expect(
      card.querySelector(".roster-account-column-weight")?.textContent,
    ).toBe("170k");
    expect(card.querySelector('input[type="checkbox"]')).not.toBeNull();
    expect(card.querySelector('[aria-label^="Actions for"]')).not.toBeNull();
    w.happyDOM.abort();
  },
);

it("keeps an in-clan desktop location green with a pin and clan name", () => {
  const host = document.createElement("div");
  host.innerHTML = render({
    account: {
      ...account,
      assigned_clan_tag: "#HOME",
      current_clan_tag: "#HOME",
      current_clan_name: "Home",
      current_clan_checked_at: "2026-10-28T12:00:00Z",
    },
    assignedClanName: "Home",
    now: Date.parse("2026-10-28T12:04:00Z"),
  });
  const now = host.querySelector(".roster-account-column-now")!;
  expect(
    now.querySelector('.player-location-pin[aria-hidden="true"]'),
  ).not.toBeNull();
  expect(now.querySelector(".player-current-clan")?.textContent).toBe("Home");
  expect(now.querySelector(".player-current-clan.is-elsewhere")).toBeNull();
  expect(now.querySelector(".is-in-clan")).not.toBeNull();
});

it("never checked location with a matching tag cannot show the green in-clan pill", () => {
  const host = document.createElement("div");
  host.innerHTML = render({
    account: {
      ...account,
      assigned_clan_tag: "#A",
      current_clan_tag: "#A",
      current_clan_name: "Home",
    },
    assignedClanName: "Home",
  });
  expect(host.querySelector(".is-in-clan")).toBeNull();
  expect(host.querySelector(".player-in-clan-pill")).toBeNull();
  expect(host.querySelector(".roster-player-placement")?.textContent).toContain(
    "location not checked yet",
  );
});
it("matches by tag first, falls back to name, colors only an elsewhere current name and keeps the pill nonshrinking", () => {
  const w = new Window({ width: 360 });
  w.document.head.innerHTML = `<style>${readFileSync("src/rosterUi/tokens.css", "utf8")}${cardCss}${accountCss}</style>`;
  for (const [tag, name, inClan] of [
    ["#A", "Different display name", true],
    [null, "Home", true],
    [null, "Warriors Unite!", false],
    ["#B", "Home", false],
  ] as const) {
    w.document.body.innerHTML = `<main class="roster-ui">${render({ account: { ...account, assigned_clan_tag: "#A", current_clan_tag: tag, current_clan_name: name, current_clan_checked_at: "2026-10-28T12:00:00Z" }, assignedClanName: "Home", now: Date.parse("2026-10-28T14:05:00Z") })}</main>`;
    const pill = w.document.querySelector(".player-in-clan-pill");
    expect(!!pill).toBe(inClan);
    if (pill) {
      expect(w.getComputedStyle(pill).flexShrink).toBe("0");
      expect(
        w.document.querySelector(".roster-player-sr-only")?.textContent,
      ).toContain("In clan, checked 2 hours 5 minutes ago.");
    } else {
      const nameColor = w.getComputedStyle(
        w.document.querySelector(".player-current-clan")!,
      ).color;
      expect(nameColor).toBe("#ff9f9f");
      expect(
        w.getComputedStyle(w.document.querySelector(".roster-player-current")!)
          .color,
      ).not.toBe(nameColor);
    }
  }
  w.happyDOM.abort();
});

it("unassigned current clans are always muted and assigned clanless wording is No clan", () => {
  const w = new Window({ width: 360 });
  w.document.head.innerHTML = `<style>${readFileSync("src/rosterUi/tokens.css", "utf8")}${cardCss}</style>`;
  for (const name of ["Other clan", null]) {
    w.document.body.innerHTML = `<main class="roster-ui">${render({ account: { ...account, current_clan_name: name, current_clan_checked_at: "2026-10-28T12:00:00Z" }, now: Date.parse("2026-10-28T12:04:00Z") })}</main>`;
    const current = w.document.querySelector(".player-current-clan")!;
    expect(current.classList.contains("is-elsewhere")).toBe(false);
    expect(w.getComputedStyle(current).color).toBe(
      w.getComputedStyle(w.document.querySelector(".roster-player-current")!)
        .color,
    );
    expect(current.textContent).toBe(name || "in no clan");
  }
  w.document.body.innerHTML = render({
    account: {
      ...account,
      assigned_clan_tag: "#A",
      current_clan_checked_at: "2026-10-28T12:00:00Z",
    },
    assignedClanName: "Amber Knights",
    now: Date.parse("2026-10-28T12:04:00Z"),
  });
  expect(
    w.document.querySelector(".roster-player-placement")?.textContent,
  ).toBe("Amber Knights No clan · 4m ago");
  expect(
    w.document.querySelector(".player-current-clan.is-elsewhere")?.textContent,
  ).toBe("No clan");
  w.happyDOM.abort();
});
it.each(["Emerald Watch", "W. U. Lazy .125"])(
  "gives %s and its inline age the full compact line at 360px",
  (name) => {
    const w = new Window({ width: 360 });
    w.document.head.innerHTML = `<style>${cardCss}</style>`;
    for (const minutes of [0, 15]) {
      w.document.body.innerHTML = `<main class="roster-ui">${render({ account: { ...account, assigned_clan_tag: "#A", current_clan_tag: "#A", current_clan_checked_at: "2026-10-28T12:00:00Z" }, assignedClanName: name, now: Date.parse("2026-10-28T12:00:00Z") + minutes * 60000 })}</main>`;
      expect(
        w.getComputedStyle(w.document.querySelector(".player-clan-status")!)
          .paddingRight,
      ).toBe("0px");
      expect(
        w.document.querySelector(".roster-player-placement")?.textContent,
      ).toBe(`${name}In clan· ${minutes ? "15m ago" : "just now"}`);
    }
    w.happyDOM.abort();
  },
);
