import type { ReactNode } from "react";
import type { StatusTone } from "./rosterUi/primitives";
import "./CardTally.css";

type Props = {
  attacks: ReactNode;
  stars: ReactNode;
  /** Outcome tone colours the numbers; the card itself stays neutral. */
  tone?: StatusTone | null;
};

/** Attacks and stars for an AccountCard `values` slot. */
export default function CardTally({ attacks, stars, tone = null }: Props) {
  const toneClass = tone ? ` is-${tone}` : "";
  return (
    <div className="card-tally">
      <span>
        <strong className={`card-tally-value${toneClass}`}>{attacks}</strong>
        <small> Attacks</small>
      </span>
      <span className="card-tally-separator"> · </span>
      <span>
        <strong className={`card-tally-value${toneClass}`}>{stars}</strong>
        <small> Stars</small>
      </span>
    </div>
  );
}
