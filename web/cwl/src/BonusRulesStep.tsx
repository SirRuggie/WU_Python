import type { ReactNode, RefObject } from "react";
import BonusAccountList from "./BonusAccountList";
import BonusBlockers from "./BonusBlockers";
import type {
  BonusAllowance,
  BonusBlockerLine,
  RaffleAccount,
} from "./bonusRaffle";
import type { Pool } from "./api";

type Props = {
  pool: Pool;
  lines: BonusBlockerLine[];
  fix: (line: BonusBlockerLine) => ReactNode;
  /** Fields are read-only without access, on an archived season, or while busy. */
  locked: boolean;
  // Main minimum
  minimum: string;
  minimumInput: RefObject<HTMLInputElement | null>;
  minimumPreview: boolean;
  canSaveMinimum: boolean;
  onMinimum: (value: string) => void;
  onSaveMinimum: () => void;
  // Count
  allowance: BonusAllowance | undefined;
  leagueMissing: boolean;
  slots: string;
  manualCount: boolean;
  countReady: boolean;
  countInput: RefObject<HTMLInputElement | null>;
  countDetails: RefObject<HTMLDetailsElement | null>;
  onSlots: (value: string) => void;
  onManualCount: (value: boolean) => void;
  // Players
  accounts: RaffleAccount[];
  /** Minimum the chips use: the saved one, or the typed one as a preview. */
  chipMinimum: number | null;
  meetsRule: number | null;
  onReview?: (account: RaffleAccount, opener: HTMLElement) => void;
  listBusy: boolean;
  /** Add player by tag (Lazy only). */
  addCandidate: ReactNode;
};

const COUNT_HINT = "Number in Clash · 1–50";

/** Step 2: Main minimum, bonus count and source, the players, and Add player by tag. */
export default function BonusRulesStep({
  pool,
  lines,
  fix,
  locked,
  minimum,
  minimumInput,
  minimumPreview,
  canSaveMinimum,
  onMinimum,
  onSaveMinimum,
  allowance,
  leagueMissing,
  slots,
  manualCount,
  countReady,
  countInput,
  countDetails,
  onSlots,
  onManualCount,
  accounts,
  chipMinimum,
  meetsRule,
  onReview,
  listBusy,
  addCandidate,
}: Props) {
  const here = (ids: string[]) => lines.filter((l) => ids.includes(l.id));
  return (
    <>
      <BonusBlockers
        lines={lines.filter((l) => !["count", "minimum"].includes(l.id))}
        fix={fix}
      />
      {pool === "main" && (
        <>
          <div className="bonus-policy">
            <label>
              Minimum attacks
              <input
                ref={minimumInput}
                type="number"
                name="minimum-attacks"
                autoComplete="off"
                inputMode="numeric"
                min="0"
                max="7"
                step="1"
                value={minimum}
                disabled={locked}
                onChange={(event) => onMinimum(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={!canSaveMinimum}
              onClick={onSaveMinimum}
            >
              Save minimum
            </button>
            <BonusBlockers lines={here(["minimum"])} fix={fix} />
          </div>
        </>
      )}
      <div className="bonus-stats">
        {leagueMissing ? (
          <label className="bonus-inline-count">
            <span>Bonuses shown in Clash</span>
            <input
              ref={countInput}
              type="number"
              name="bonus-count"
              autoComplete="off"
              inputMode="numeric"
              min="1"
              max="50"
              step="1"
              value={slots}
              disabled={locked}
              onChange={(event) => {
                onManualCount(true);
                onSlots(event.target.value);
              }}
            />
            <small className="bonus-field-hint">{COUNT_HINT}</small>
          </label>
        ) : (
          <div>
            <strong>
              {manualCount && countReady
                ? Number(slots)
                : allowance?.status === "ready"
                  ? allowance.total
                  : "—"}
            </strong>
            <span>
              Total bonus allowance
              {manualCount && countReady ? " · staff count" : ""}
            </span>
          </div>
        )}
        <div>
          <strong>{accounts.length}</strong>
          <span>Players</span>
        </div>
        <div role="status">
          <strong>{meetsRule ?? "—"}</strong>
          <span>meet rule</span>
        </div>
      </div>
      <BonusBlockers lines={here(["count"])} fix={fix} />
      {pool === "lazy" && (
        <p className="bonus-rules-line">
          Lazy rules · 4+ attacks, or 3 attacks and 8+ stars · No bonus in the
          last 3 seasons
        </p>
      )}
      <div className="bonus-candidates-heading">
        <h3 data-dashboard-focus-fallback tabIndex={-1}>
          Players
        </h3>
        {minimumPreview && (
          <p className="bonus-preview-note">Preview · not saved</p>
        )}
      </div>
      <BonusAccountList
        accounts={accounts}
        minimum={chipMinimum}
        onReview={onReview}
        busy={listBusy}
        searchable
      />
      {addCandidate}
      <details
        ref={countDetails}
        className="bonus-secondary bonus-count-source"
      >
        <summary>Bonus count and source</summary>
        <p className="bonus-allowance-reason">
          {allowance?.reason || "Check Clash now to see the allowance."}
        </p>
        <p>
          {allowance?.league || "League unknown"}
          {allowance?.team_size
            ? ` · ${allowance.team_size} vs ${allowance.team_size}`
            : ""}{" "}
          · {allowance?.completed_wars ?? 0}/{allowance?.rounds ?? "?"} wars
          complete
          {allowance?.base != null
            ? ` · ${allowance.base} base + ${allowance.wins} wins${allowance.status === "ready" ? ` = ${allowance.total}` : ""}`
            : ""}
        </p>
        <label className="bonus-check">
          <input
            type="checkbox"
            name="manual-count"
            checked={manualCount}
            disabled={locked}
            onChange={(event) => onManualCount(event.target.checked)}
          />
          <span>Use the total shown in Clash</span>
        </label>
        {manualCount && !leagueMissing && (
          <label className="bonus-count-field">
            Total bonuses shown in Clash
            <input
              ref={countInput}
              type="number"
              name="bonus-count"
              autoComplete="off"
              inputMode="numeric"
              min="1"
              max="50"
              step="1"
              value={slots}
              disabled={locked}
              onChange={(event) => onSlots(event.target.value)}
            />
            <small className="bonus-field-hint">{COUNT_HINT}</small>
          </label>
        )}
        {manualCount && (
          <p className="bonus-caution">
            Staff-confirmed count; not API-verified.
          </p>
        )}
      </details>
    </>
  );
}
