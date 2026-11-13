import DiscordIdentity from "../DiscordIdentity";
import type useDiscordIdentities from "../useDiscordIdentities";
import { strikeCountLabel } from "../strikeCountLabel";
import { importEmptyText, isCwlRecord } from "../strikeHistoryView";
import { selectedImportEntries } from "../strikeSelections";
import { dateText, reviewCount } from "./format";
import type { ActiveImportJob, ImportPreview } from "./types";

export default function StrikesImportPanel({
  open: importOpen,
  onToggle,
  busy,
  importJob,
  preview,
  excluded,
  setExcluded,
  jobRetryPaused,
  discordProfiles,
  onPreview,
  onApply,
  onRetryStatus,
}: {
  open: boolean;
  onToggle: (open: boolean) => void;
  busy: boolean;
  importJob: ActiveImportJob | null;
  preview: ImportPreview | null;
  excluded: string[];
  setExcluded: (update: (current: string[]) => string[]) => void;
  jobRetryPaused: boolean;
  discordProfiles: ReturnType<typeof useDiscordIdentities>;
  onPreview: () => void;
  onApply: () => void;
  onRetryStatus: () => void;
}) {
  const importSelected = selectedImportEntries(
    preview?.entries || [],
    excluded,
  );
  const importStrikes = importSelected.filter(
    (item) => item.will_strike,
  ).length;
  const importAccounts = new Set(
    importSelected
      .filter((item) => item.will_strike)
      .map((item) => item.player_tag),
  ).size;
  const importHistory = importSelected.length - importStrikes;
  const deferredAccounts = preview?.deferred_accounts || [];
  const deferredCount = preview?.deferred_count ?? deferredAccounts.length;
  return (
    <details
      className="card strikes-import-settings"
      open={importOpen}
      onToggle={(event) => onToggle(event.currentTarget.open)}
    >
      <summary>
        Import past wars
        {importJob ? " · In progress" : preview ? " · Preview ready" : ""}
      </summary>
      <div className="strikes-import-content">
        <div className="strikes-form">
          <h2>Import recent wars</h2>
          <p>
            Check up to 60 days of wars. Regular war misses may add strikes; CWL
            is records only.
          </p>
          <button
            className="primary"
            disabled={busy || !!importJob}
            onClick={onPreview}
          >
            {busy || importJob?.phase === "preview"
              ? "Checking wars…"
              : preview
                ? "Check again"
                : "Check past wars"}
          </button>
        </div>
        {importJob && (
          <div className="strikes-job-status" role="status">
            <span>
              {jobRetryPaused
                ? "Connection paused. Retry status."
                : importJob.phase === "preview"
                  ? "Checking wars… You can return later."
                  : "Importing records… You can return later."}
            </span>
            {jobRetryPaused && (
              <button onClick={onRetryStatus}>Retry status</button>
            )}
          </div>
        )}
        {preview && (
          <>
            <p className="strikes-import-summary" aria-live="polite">
              Adds {strikeCountLabel(importStrikes, "strike")} to{" "}
              {strikeCountLabel(importAccounts, "account")} ·{" "}
              {strikeCountLabel(importHistory, "history-only record")}
            </p>
            <p>
              ClashKing (import) ·{" "}
              {strikeCountLabel(preview.complete_wars, "complete war")} ·{" "}
              {strikeCountLabel(preview.incomplete_wars, "skipped war")} ·{" "}
              {reviewCount(deferredCount)}
            </p>
            <details className="card strikes-coverage">
              <summary>Coverage by clan</summary>
              {preview.coverage.map((item) => (
                <div key={item.clan_name}>
                  <strong>{item.clan_name}</strong>
                  <span>
                    {item.error
                      ? "Unavailable"
                      : `${strikeCountLabel(item.wars, "war")}${item.skipped || item.processing_skipped_wars ? ` · ${strikeCountLabel((item.skipped || 0) + (item.processing_skipped_wars || 0), "skipped war")}` : ""}${item.deferred_accounts ? ` · ${reviewCount(item.deferred_accounts)}` : ""} · ${dateText(item.earliest)} to ${dateText(item.latest)}`}
                  </span>
                </div>
              ))}
            </details>
            <details className="strikes-import-review">
              <summary>
                Review selected records ({preview.entries.length})
              </summary>
              {preview.entries.length === 0 && (
                <div className="card strikes-empty">
                  {importEmptyText(
                    preview.entries,
                    deferredCount,
                    preview.incomplete_wars,
                  )}
                </div>
              )}
              <div className="strikes-list">
                {preview.entries.map((item) => (
                  <div className="card strikes-import-row" key={item.key}>
                    <div>
                      <strong>{item.player_name}</strong>
                      <small>
                        {item.player_tag} · {item.clan_name} ·{" "}
                        {dateText(item.war_end)} ·{" "}
                        <DiscordIdentity
                          userId={item.discord_id}
                          linkStatus={
                            "link_status" in item
                              ? (item.link_status as string)
                              : undefined
                          }
                          resolvedMember={
                            discordProfiles.members[item.discord_id || ""] ||
                            null
                          }
                          resolving={discordProfiles.loading}
                          variant="compact"
                        />
                      </small>
                      <span>
                        {isCwlRecord(item)
                          ? `CWL · ${item.duplicate ? "Already recorded" : item.attacks_used === 0 || item.missed_attacks > 0 ? "Attack missed" : "Attack used"} · No strikes`
                          : `${item.missed_attacks} missed · ${item.duplicate ? "Already recorded" : item.exempt ? "Exempt" : item.will_strike ? "Strike" : "Record only"}`}
                      </span>
                    </div>
                    {!item.duplicate && (
                      <label className="strikes-check">
                        <input
                          type="checkbox"
                          checked={!excluded.includes(item.key)}
                          disabled={importJob?.phase === "apply"}
                          onChange={(event) =>
                            setExcluded((current) =>
                              event.target.checked
                                ? current.filter((key) => key !== item.key)
                                : [...current, item.key],
                            )
                          }
                        />
                        {isCwlRecord(item)
                          ? "Save CWL record"
                          : item.exempt
                            ? "Save exempt record"
                            : item.will_strike
                              ? "Add strike"
                              : "Save record"}
                      </label>
                    )}
                  </div>
                ))}
              </div>
            </details>
            {deferredCount > 0 && (
              <details className="card strikes-needs-review">
                <summary>Needs review ({deferredCount})</summary>
                <div className="strikes-review-list">
                  {deferredAccounts.map((item, index) => (
                    <div key={`${item.player_tag}-${item.war_end || index}`}>
                      <strong>{item.player_name || item.player_tag}</strong>
                      <small>
                        {item.player_tag} · {item.clan_name}
                        {item.war_end ? ` · ${dateText(item.war_end)}` : ""}
                      </small>
                      <span>
                        {item.missed_attacks != null
                          ? `${item.missed_attacks} missed · `
                          : ""}
                        {item.reason || "Account link needs review."}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            )}
            <div className="strikes-import-apply">
              <span>
                {strikeCountLabel(importSelected.length, "record")} selected
              </span>
              <button
                className="primary"
                disabled={busy || !!importJob || importSelected.length === 0}
                onClick={onApply}
              >
                {busy || importJob?.phase === "apply"
                  ? "Importing…"
                  : `Add ${strikeCountLabel(importStrikes, "strike")}`}
              </button>
            </div>
          </>
        )}
      </div>
    </details>
  );
}
