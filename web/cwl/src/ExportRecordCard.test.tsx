// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import ExportRecordCard from "./ExportRecordCard";
import ExportRosterView from "./ExportRosterView";
import ExportWinnersView from "./ExportWinnersView";
it("groups shared roster rows Main before Lazy, with player/tag/TH/weight and escaped names", () => {
  const html = renderToStaticMarkup(
    <ExportRosterView
      kind="accounts"
      rows={[
        {
          pool: "lazy",
          assigned_clan_name: "A lazy",
          player_name: "Lazy",
          tag: "#P2Y",
          town_hall: 16,
          effective_weight: 179000,
        },
        {
          pool: "main",
          assigned_clan_name: "Z main",
          player_name: "<script>",
          tag: "#Q2Y",
          town_hall: 15,
          effective_weight: 160000,
        },
      ]}
    />,
  );
  expect(html.indexOf("Z main")).toBeLessThan(html.indexOf("A lazy"));
  expect(html).toContain("179k");
  expect(html).toContain("TH 16");
  expect(html).toContain("#P2Y");
  expect(html).toContain("&lt;script&gt;");
  expect(html).not.toContain("<script>");
  expect(html).not.toContain("Attacks");
});
it("shows Imported and hides voided winners, with Main first", () => {
  const html = renderToStaticMarkup(
    <ExportWinnersView
      rows={[
        {
          pool: "lazy",
          clan_name: "A lazy",
          player_name: "Imported name",
          tag: "#P2Y",
          source: "import",
        },
        {
          pool: "main",
          clan_name: "Z main",
          player_name: "Main name",
          tag: "#Q2Y",
          town_hall: 17,
          attacks: 7,
          stars: 15,
        },
        {
          pool: "main",
          clan_name: "Z main",
          player_name: "Voided name",
          voided_at: "now",
        },
      ]}
    />,
  );
  expect(html).toContain("Imported");
  expect(html).not.toContain("Voided name");
  expect(html).toContain("TH 17 · #Q2Y");
  expect(html).toContain("Attacks");
  expect(html).toContain(">15<");
  // Unknown Town Hall: no "TH —" text in the meta line.
  expect(html).not.toContain("TH — ·");
  expect(html.indexOf("Z main")).toBeLessThan(html.indexOf("A lazy"));
});
it("preserves signup tally and capture status", () => {
  const html = renderToStaticMarkup(
    <ExportRecordCard
      kind="participation"
      row={{
        player_name: "Fixture",
        attacks: 2,
        stars: 5,
        display_status: { label: "Final results" },
      }}
    />,
  );
  expect(html).toContain("Final results");
  expect(html).toContain("Attacks");
});
it("keeps saved history notes in a closed disclosure", () => {
  const html = renderToStaticMarkup(
    <ExportRecordCard
      kind="participation-history"
      row={{
        player_name: "Fixture",
        attacks: 0,
        stars: 0,
        notes: "<b>note</b>",
        updated_at: "2026-11-01",
      }}
    />,
  );
  expect(html).toContain("Saved details");
  expect(html).toContain("&lt;b&gt;note&lt;/b&gt;");
  expect(html).not.toContain("<details open");
});
