import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import StrikeStreak from "./StrikeStreak";
import ReplacementDeparture from "./ReplacementDeparture";

it.each([
  [0, "Streak: 0 wars played · 2 more to lose a strike"],
  [1, "Streak: 1 war played · 1 more to lose a strike"],
  [2, "Streak: 2 wars played · 2 more to lose a strike"],
  [3, "Streak: 3 wars played · 1 more to lose a strike"],
  [4, "Streak: 4 wars played · 2 more to clear all strikes"],
  [5, "Streak: 5 wars played · 1 more to clear all strikes"],
])("shows current streak %s and the next milestone", (count, expected) => {
  expect(renderToStaticMarkup(<StrikeStreak streak={{ count }} />)).toContain(
    expected,
  );
});

it.each([
  undefined,
  null,
  { count: -1 },
  { count: 6 },
  { count: NaN },
  { count: 1.5 },
])(
  "does not turn unavailable/malformed streak data into zero: %j",
  (streak) => {
    expect(renderToStaticMarkup(<StrikeStreak streak={streak} />)).toContain(
      "Streak: Unavailable",
    );
  },
);

it("keeps loading separate from known streak data", () => {
  expect(
    renderToStaticMarkup(<StrikeStreak loading streak={{ count: 3 }} />),
  ).toContain("Streak: Loading…");
});

it("shows departed grace with escaped last-seen clan and a machine-readable timestamp", () => {
  const html = renderToStaticMarkup(
    <ReplacementDeparture clan="<Clan>" seenAt="2026-10-30T12:00:00Z" />,
  );
  expect(html).toContain("Left clan · 48-hour grace period");
  expect(html).toContain("Last seen in &lt;Clan&gt;");
  expect(html).toContain('dateTime="2026-10-30T12:00:00.000Z"');
});

it.each([null, "broken"])(
  "labels missing/invalid last-seen time honestly: %s",
  (seenAt) => {
    expect(
      renderToStaticMarkup(
        <ReplacementDeparture clan="Clan" seenAt={seenAt} />,
      ),
    ).toContain("Time unavailable");
  },
);
