import { strikeCountLabel } from "./strikeCountLabel";
// Prompt 23 will wire the configurable setting into every consumer.
export const DEFAULT_STRIKE_LIMIT = 4;

type HelpPart = { text: string; strong?: boolean };

/** Canonical wording for the panel and future member-card/plain-text consumers. */
export function strikeHelpLines(limit = DEFAULT_STRIKE_LIMIT): HelpPart[][] {
  const threshold =
    Number.isInteger(limit) && limit > 0 ? limit : DEFAULT_STRIKE_LIMIT;
  return [
    [
      { text: "You get 1 strike", strong: true },
      { text: " if you miss " },
      { text: "both", strong: true },
      { text: " attacks in a war." },
    ],
    [
      { text: "Missing " },
      { text: "1", strong: true },
      { text: " attack gives " },
      { text: "no strike", strong: true },
      { text: ", but it breaks your streak." },
    ],
    [{ text: "CWL", strong: true }, { text: " never gives strikes." }],
    [
      { text: "Play 2 wars in a row", strong: true },
      { text: " (use both attacks) → " },
      { text: "1 strike is removed", strong: true },
      { text: "." },
    ],
    [
      { text: "Play 6 wars in a row", strong: true },
      { text: " → " },
      { text: "all your strikes are removed", strong: true },
      { text: "." },
    ],
    [
      { text: "A strike also goes away by itself after " },
      { text: "60 days", strong: true },
      { text: "." },
    ],
    [
      { text: "Approved leave", strong: true },
      { text: " pauses strikes. Ask a leader before you go." },
    ],
    [
      { text: "At " },
      { text: `${strikeCountLabel(threshold, "strike")}`, strong: true },
      { text: ", leaders may replace you in the clan." },
    ],
  ];
}

export function strikeHelpText(limit = DEFAULT_STRIKE_LIMIT): string {
  return strikeHelpLines(limit)
    .map((line) => line.map((part) => part.text).join(""))
    .join("\n");
}
