import type { ReactNode } from "react";
import type { BonusBlockerLine } from "./bonusRaffle";

/** One line per blocker, with its fix beside it. Nothing else lists blockers. */
export default function BonusBlockers({
  lines,
  fix,
}: {
  lines: BonusBlockerLine[];
  fix: (line: BonusBlockerLine) => ReactNode;
}) {
  if (!lines.length) return null;
  return (
    <ul className="bonus-blockers">
      {lines.map((line) => (
        <li key={line.id} className={line.bar ? "is-alert" : undefined}>
          {fix(line)}
        </li>
      ))}
    </ul>
  );
}
