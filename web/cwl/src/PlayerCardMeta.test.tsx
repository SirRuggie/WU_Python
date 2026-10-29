// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { Window } from "happy-dom";
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import PlayerCardMeta from "./PlayerCardMeta";
import type { RosterAccount } from "./roster";

it.each(["player-card-responsive", "player-card-compact"])(
  "keeps a nine-character locked Lazy tag fixed and only the pool shrinkable in %s at 360px",
  (layout) => {
    const w = new Window({ width: 360 });
    w.document.head.innerHTML = `<style>${readFileSync("src/PlayerCard.css", "utf8")}</style>`;
    const markup = renderToStaticMarkup(
      <PlayerCardMeta
        account={
          {
            tag: "#QG02CY8LG",
            town_hall: 18,
            pool: "lazy",
            kept: true,
          } as RosterAccount
        }
      />,
    );
    w.document.body.innerHTML = `<main class="roster-ui"><article class="player-card ${layout}">${markup}</article></main>`;
    const row = w.document.querySelector(".player-card-meta")!;
    const core = row.querySelector(".player-card-meta-core")!;
    const pool = row.querySelector(".player-card-meta-pool")!;
    const lock = row.querySelector("svg")!;
    expect(core.textContent).toBe("TH18 · #QG02CY8LG");
    expect(pool.textContent).toBe("· Lazy");
    expect(w.getComputedStyle(row).whiteSpace).toBe("nowrap");
    expect(w.getComputedStyle(row).flexWrap).toBe("nowrap");
    expect(w.getComputedStyle(core).flexShrink).toBe("0");
    expect(w.getComputedStyle(lock).flexShrink).toBe("0");
    expect(w.getComputedStyle(pool).textOverflow).toBe("ellipsis");
    expect(w.getComputedStyle(pool).minWidth).toMatch(/^0(px)?$/);
    expect(row.querySelector(".sr-only")?.textContent).toBe(
      "Town Hall 18. #QG02CY8LG. Lazy CWL. Locked placement.",
    );
    w.happyDOM.abort();
  },
);
it("keeps full Main CWL words accessible and honors hidden pool metadata", () => {
  const account = {
    tag: "#QG02CY8LG",
    town_hall: 18,
    pool: "main",
    kept: false,
  } as RosterAccount;
  expect(renderToStaticMarkup(<PlayerCardMeta account={account} />)).toContain(
    "Main CWL",
  );
  const hidden = renderToStaticMarkup(
    <PlayerCardMeta account={account} showPool={false} />,
  );
  expect(hidden).not.toContain("Main");
  expect(hidden).not.toContain("Locked placement");
});
