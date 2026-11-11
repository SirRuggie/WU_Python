import { useState, type MouseEvent } from "react";
import type { Pool } from "./api";
import {
  bonusStepStates,
  type BonusStatus,
  type BonusStep,
} from "./bonusStatus";
import { plainClick, resultsStateQuery } from "./resultsUrlState";
import type { OutcomeFilter } from "./participationOutcome";
import "./BonusStepBar.css";

type Props = {
  seasonId: string;
  pool: Pool;
  clan: string;
  status: BonusStatus | null;
  failed: boolean;
  onRetry: () => void;
  /** Steps whose page the user cannot open render as text. */
  canOpen: (step: BonusStep) => boolean;
  onSelect: (step: BonusStep, query: string) => void;
};

export function bonusStepHref(
  seasonId: string,
  step: BonusStep,
  pool: Pool,
  clan: string,
  outcome?: OutcomeFilter,
) {
  const query = resultsStateQuery({
    pool,
    clan: clan || undefined,
    outcome: step === "results" ? outcome : undefined,
    step: step === "results" ? undefined : step,
  });
  const path = step === "results" ? "/cwl/results" : "/cwl/bonuses";
  return {
    query,
    href: `${path}?season=${encodeURIComponent(seasonId)}${query ? `&${query}` : ""}`,
  };
}

/** Results → Eligibility → Draw → Approval → Announcement for one hosting clan. */
export default function BonusStepBar({
  seasonId,
  pool,
  clan,
  status,
  failed,
  onRetry,
  canOpen,
  onSelect,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const host = clan
    ? status?.pools[pool].find((item) => item.tag === clan) || null
    : null;
  const loading = !status && !failed;
  const steps = bonusStepStates(host, pool, status?.main_minimum ?? null);
  const active = steps.findIndex(
    (step) => step.state === "current" || step.state === "blocked",
  );
  const summary = !clan
    ? "Bonus steps"
    : loading
      ? "Bonus steps · …"
      : failed || !status
        ? "Bonus steps"
        : active < 0
          ? host
            ? "All 5 steps done"
            : "Bonus steps"
          : `Step ${active + 1} of 5 · ${steps[active].label}`;
  const select = (step: BonusStep, query: string) => (event: MouseEvent) => {
    if (!plainClick(event)) return;
    event.preventDefault();
    onSelect(step, query);
  };
  return (
    <nav className="bonus-step-bar" aria-label="Bonus progress">
      <button
        type="button"
        className="bonus-step-compact"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span>{summary}</span>
        <span className="bonus-step-dots" aria-hidden="true">
          {steps.map((step, index) => (
            <span
              key={step.id}
              className={`bonus-step-dot is-${failed || loading ? "todo" : step.state}${index === active ? " is-active" : ""}`}
            />
          ))}
        </span>
      </button>
      <ol className={`bonus-step-list${expanded ? " is-expanded" : ""}`}>
        {steps.map((step, index) => {
          const { href, query } = bonusStepHref(seasonId, step.id, pool, clan);
          const state = failed || loading ? "todo" : step.state;
          const label = (
            <>
              <span className="bonus-step-mark" aria-hidden="true">
                {loading
                  ? "…"
                  : state === "done"
                    ? "✓"
                    : state === "blocked"
                      ? "!"
                      : index + 1}
              </span>
              <span className="bonus-step-name">{step.label}</span>
              {state === "blocked" && (
                <small className="bonus-step-reason">{step.reason}</small>
              )}
              {state === "done" && <span className="sr-only"> · Done</span>}
            </>
          );
          return (
            <li
              key={step.id}
              className={`bonus-step is-${state}`}
              data-step={step.id}
            >
              {canOpen(step.id) ? (
                <a
                  href={href}
                  aria-current={
                    state === "current" || state === "blocked"
                      ? "step"
                      : undefined
                  }
                  onClick={select(step.id, query)}
                >
                  {label}
                </a>
              ) : (
                <span
                  className="bonus-step-text"
                  aria-current={
                    state === "current" || state === "blocked"
                      ? "step"
                      : undefined
                  }
                >
                  {label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {failed && (
        <p className="bonus-step-unavailable">
          Status unavailable ·{" "}
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        </p>
      )}
    </nav>
  );
}
