import type { RefObject } from "react";
import { warMatchup, warSummary } from "../strikeHistoryView";
import { dateText } from "./format";
import type { War } from "./types";

export default function StrikesFindWar({
  inputRef: warSearchRef,
  query: warQuery,
  onQuery,
  loading: warLoading,
  error: warError,
  wars,
  incomplete: warIncomplete,
  total: warTotal,
  page: warPage,
  setPage: setWarPage,
  onChoose,
  onRetry,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  query: string;
  onQuery: (value: string) => void;
  loading: boolean;
  error: string;
  wars: War[];
  incomplete: boolean;
  total: number;
  page: number;
  setPage: (update: (value: number) => number) => void;
  onChoose: (war: War) => void;
  onRetry: () => void;
}) {
  return (
    <div className="card strikes-war-search">
      <label>
        Find war
        <input
          ref={warSearchRef}
          type="search"
          value={warQuery}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Opponent, clan, or date"
        />
      </label>
      {warLoading ? (
        <p role="status">Finding wars…</p>
      ) : warError ? (
        <p role="alert">
          {warError}
          <button onClick={onRetry}>Retry war search</button>
        </p>
      ) : wars.length === 0 ? (
        <p>No saved wars found.</p>
      ) : (
        <div className="strikes-war-results">
          {wars.map((war) => (
            <button key={war.war_key} onClick={() => onChoose(war)}>
              <strong>{warMatchup(war.clan_name, war.opponent_name)}</strong>
              <span>
                {dateText(war.war_end)} ·{" "}
                {war.source_label || "Source unavailable"} ·{" "}
                {war.manual_review_required
                  ? `${war.review_message || "Staff review required"} · Streak hold`
                  : war.incomplete
                    ? `${war.review_message || "War ended before final check: review in Find war"} · No automatic strikes`
                    : warSummary(war)}
              </span>
            </button>
          ))}
        </div>
      )}
      {warIncomplete && (
        <p role="status">
          Some opponent names are unavailable. Search by tag or date, or retry.
        </p>
      )}
      {warTotal > 25 && (
        <div className="strikes-pages">
          <button
            disabled={warLoading || warPage === 0}
            onClick={() => setWarPage((value) => value - 1)}
          >
            Previous wars
          </button>
          <span>
            {warPage * 25 + 1}–{Math.min((warPage + 1) * 25, warTotal)} of{" "}
            {warTotal}
          </span>
          <button
            disabled={warLoading || (warPage + 1) * 25 >= warTotal}
            onClick={() => setWarPage((value) => value + 1)}
          >
            Next wars
          </button>
        </div>
      )}
    </div>
  );
}
