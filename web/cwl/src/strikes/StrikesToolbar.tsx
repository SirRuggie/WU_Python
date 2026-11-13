import { warMatchup } from "../strikeHistoryView";
import { dateText } from "./format";
import type { StrikeAccount, War } from "./types";

export default function StrikesToolbar({
  canAdd,
  busy,
  loading,
  status,
  selectedAccount,
  selectedWar,
  showWarSearch,
  onBack,
  onStatus,
  onAdd,
  onToggleWarSearch,
  onRefresh,
  onClearWar,
}: {
  canAdd: boolean;
  busy: boolean;
  loading: boolean;
  status: string;
  selectedAccount: StrikeAccount | null;
  selectedWar: War | null;
  showWarSearch: boolean;
  onBack: () => void;
  onStatus: (status: string) => void;
  onAdd: () => void;
  onToggleWarSearch: () => void;
  onRefresh: () => void;
  onClearWar: () => void;
}) {
  return (
    <>
      {(selectedAccount || selectedWar) && (
        <div
          className={`strikes-toolbar${selectedAccount ? " strikes-toolbar-player" : !selectedWar ? " strikes-toolbar-actions" : ""}`}
        >
          {selectedAccount && <button onClick={onBack}>← Players</button>}
          {selectedAccount && (
            <label>
              Status
              <select
                value={status}
                disabled={!!selectedWar}
                onChange={(event) => onStatus(event.target.value)}
              >
                <option value="active">Active strikes</option>
                <option value="expired">Expired strikes</option>
                <option value="removed">Removed strikes</option>
                <option value="recorded">One attack missed (no strike)</option>
                <option value="cwl">CWL miss (no strike)</option>
                <option value="mismatch">Mismatch war (no strike)</option>
                <option value="exempt">Exempt (no strike)</option>
                <option value="all">Everything</option>
              </select>
            </label>
          )}

          {canAdd && (
            <button className="primary" disabled={busy} onClick={onAdd}>
              Add strike
            </button>
          )}
          {!selectedAccount && !selectedWar && (
            <button
              aria-expanded={showWarSearch}
              onClick={(event) => {
                event.currentTarget.closest("details")?.removeAttribute("open");
                onToggleWarSearch();
              }}
            >
              {showWarSearch ? "Close war search" : "Find war"}
            </button>
          )}
        </div>
      )}
      {!selectedAccount && selectedWar && (
        <div className="strikes-war-tools">
          {selectedWar && (
            <button disabled={busy || loading} onClick={onRefresh}>
              Refresh records
            </button>
          )}
          <button
            aria-expanded={showWarSearch}
            onClick={(event) => {
              event.currentTarget.closest("details")?.removeAttribute("open");
              onToggleWarSearch();
            }}
          >
            {showWarSearch ? "Close war search" : "Find war"}
          </button>
          {selectedWar && (
            <div className="strikes-selected-war">
              <span>
                {warMatchup(selectedWar.clan_name, selectedWar.opponent_name)} ·{" "}
                {dateText(selectedWar.war_end)} ·{" "}
                {selectedWar.source_label || "Source unavailable"}
                {selectedWar.manual_review_required
                  ? " · Quarantined · Streak hold"
                  : selectedWar.mismatch
                    ? " · ⊖ Mismatch war (no strike)"
                    : selectedWar.no_attack
                      ? " · ⊖ No-attack war (no strike)"
                      : selectedWar.incomplete
                        ? " · Incomplete · No automatic strikes"
                        : " · All records"}
              </span>
              {selectedWar.war_plan_reason && (
                <span>{selectedWar.war_plan_reason}</span>
              )}
              <button onClick={onClearWar}>Clear war</button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
