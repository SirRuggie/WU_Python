// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import ExportRecordCard, { type ExportKind } from "./ExportRecordCard";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const show = async (kind: ExportKind, row: Record<string, unknown>) => {
  await act(async () =>
    root.render(<ExportRecordCard kind={kind} row={row} />),
  );
  return host.querySelector("article")!;
};
const base = {
  player_name: "rufen",
  tag: "#20YRRRY9R",
  town_hall: 16,
  pool: "lazy",
  assigned_clan_name: "W. U. Lazy.128",
};

it("Roster rows use the shared card: TH, tag, CWL and clan, tally, weight", async () => {
  const card = await show("accounts", {
    ...base,
    effective_weight: 179000,
    participation_attacks: 5,
    participation_stars: 10,
  });
  expect(card.classList).toContain("shared-account-card");
  expect(card.classList).toContain("account-card-plain");
  expect(card.querySelector(".account-card-meta")!.textContent).toBe(
    "TH 16 · #20YRRRY9R · Lazy CWL · W. U. Lazy.128",
  );
  expect(card.querySelector(".card-tally")!.textContent).toBe(
    "5 Attacks · 10 Stars",
  );
  expect(card.querySelector(".account-card-flags")!.textContent).toBe(
    "Weight 179k",
  );
});

it("a result for another assignment shows the reason, not a tally", async () => {
  const card = await show("accounts", {
    ...base,
    effective_weight: null,
    participation_matches_roster: false,
    participation_recorded_clan_name: "W. U.Lazy.126",
    participation_attacks: 7,
    participation_stars: 15,
  });
  expect(card.querySelector(".card-tally")).toBeNull();
  expect(card.querySelector(".account-card-flags")!.textContent).toBe(
    "Recorded for another assignment: W. U.Lazy.126 · Weight —",
  );
});

it("Signups rows show the Clash capture status with the tally", async () => {
  const card = await show("participation", {
    ...base,
    attacks: 2,
    stars: 5,
    source_status: "complete",
    display_status: { code: "complete", label: "Final results" },
  });
  expect(card.querySelector(".card-tally")!.textContent).toBe(
    "2 Attacks · 5 Stars",
  );
  expect(card.querySelector(".account-card-flags")!.textContent).toBe(
    "Clash capture: Final results",
  );
});

it("Results history keeps saved notes behind a disclosure", async () => {
  const card = await show("participation-history", {
    ...base,
    attacks: 0,
    stars: 0,
    source_status: "complete",
    notes: "Fixture note",
    updated_at: "2026-10-12T10:00:00Z",
  });
  expect(card.querySelector(".card-tally")!.textContent).toBe(
    "0 Attacks · 0 Stars",
  );
  const details = card.querySelector("details.export-record-details")!;
  expect(details.textContent).toContain("Fixture note");
  expect(details.hasAttribute("open")).toBe(false);
});

it("Saved bonus history shows the selection as a pill and keeps names as text", async () => {
  const card = await show("bonus-history", {
    player_name: "<b>@everyone</b>",
    tag: "#P2Y",
    clan_name: "W. U. Lazy.128",
    cycle: "2026-10",
    voided_at: "2026-10-13T10:00:00Z",
    void_reason: "Left the family",
    confirmed_at: "2026-10-12T10:00:00Z",
  });
  expect(card.querySelector("b")).toBeNull();
  expect(card.querySelector(".roster-ui-status")!.textContent).toBe(
    "Voided selection",
  );
  expect(card.querySelector(".account-card-flags")!.textContent).toContain(
    "Left the family",
  );
});
