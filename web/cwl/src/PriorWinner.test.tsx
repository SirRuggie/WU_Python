// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";
import PriorWinner, { winnerMonth } from "./PriorWinner";
import BonusAccountCard from "./BonusAccountCard";
import type { RaffleAccount } from "./bonusRaffle";
const host = document.createElement("div");
const root = createRoot(host);
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(async () => {
  await act(async () => root.render(null));
});
const account = {
  pool: "lazy",
  sit_out_excluded: true,
  prior_winner_cycle: "2026-10",
  eligible_again: "2027-02",
};
it("renders the latest win month and eligible-again year in Details", async () => {
  await act(async () => root.render(<PriorWinner account={account} details />));
  expect(host.textContent).toBe(
    "Prior winner · Oct 2026Eligible again: February 2027",
  );
  expect(host.querySelector(".roster-ui-chip")).toBeTruthy();
});
it("suppresses a pill after eligibility is overridden or the sit-out expires; Main never gets one", async () => {
  for (const row of [
    { ...account, sit_out_excluded: false },
    { ...account, pool: "main" },
  ]) {
    await act(async () => root.render(<PriorWinner account={row} details />));
    expect(host.textContent).toBe("");
  }
});
it("puts a prior-winner chip on clan step cards without repeating the backend exclusion", async () => {
  const row = {
    ...account,
    tag: "#P2Y",
    player_name: "Fixture",
    attacks: 4,
    stars: 9,
    assigned_clan_tag: "#C2Y",
    source_complete: true,
    exclusion: "Prior winner (Oct 2026)",
  } as RaffleAccount;
  await act(async () =>
    root.render(
      <BonusAccountCard account={row} mode="candidates" minimum={null} />,
    ),
  );
  expect(host.textContent?.match(/Prior winner/g)).toHaveLength(1);
});
it("formats months in UTC and rejects malformed cycles", () => {
  expect(winnerMonth("2027-01")).toBe("Jan 2027");
  expect(winnerMonth("2026-13")).toBe("");
});
