import { useEffect, useId, useRef, useState } from "react";
import DiscordIdentity from "./DiscordIdentity";
import useDiscordIdentities from "./useDiscordIdentities";
import {
  canUseSyncedResults,
  parseOptionalCount,
  participationValidation,
  syncStatusLabel,
  type ParticipationAccount,
} from "./participation";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Could not save results.";
const dateText = (value: string) => new Date(value).toLocaleString();

type Props = {
  account: ParticipationAccount;
  publicationVersion: number | null;
  readonly: boolean;
  locked: boolean;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onSave: (
    account: ParticipationAccount,
    revision: number,
    publicationVersion: number | null,
    sourceCheckedAt: string | null,
    attacks: number | null,
    stars: number | null,
    notes: string,
  ) => Promise<ParticipationAccount>;
  onReset: (account: ParticipationAccount) => Promise<ParticipationAccount>;
  onDirty: (tag: string, dirty: boolean) => void;
};

const values = (row: ParticipationAccount) => ({
  attacks: row.attacks === null ? "" : String(row.attacks),
  stars: row.stars === null ? "" : String(row.stars),
  notes: row.notes,
});

export default function ParticipationRecord({
  account,
  publicationVersion,
  readonly,
  locked,
  open,
  onOpen,
  onClose,
  onSave,
  onReset,
  onDirty,
}: Props) {
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const people = useDiscordIdentities(
    [account.user_id, account.updated_by],
    open,
  );
  const [draft, setDraft] = useState(() => values(account));
  const [base, setBase] = useState(() => ({
    ...values(account),
    revision: account.revision,
    publicationVersion,
    rosterToken: account.roster_token,
    sourceCheckedAt: account.source_checked_at ?? null,
  }));
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState("");
  const changed =
    draft.attacks !== base.attacks ||
    draft.stars !== base.stars ||
    draft.notes !== base.notes;
  const current = values(account);
  const stale =
    account.roster_token !== base.rosterToken ||
    account.revision !== base.revision ||
    publicationVersion !== base.publicationVersion ||
    (account.source_checked_at ?? null) !== base.sourceCheckedAt ||
    current.attacks !== base.attacks ||
    current.stars !== base.stars ||
    current.notes !== base.notes;
  const hasOverride = !!(
    account.attacks_override ||
    account.stars_override ||
    account.roster_changed
  );
  const hasSource =
    (account.source_attacks !== null && account.source_attacks !== undefined) ||
    (account.source_stars !== null && account.source_stars !== undefined);
  const canReset = canUseSyncedResults(account);
  const attackValue = parseOptionalCount(draft.attacks);
  const starValue = parseOptionalCount(draft.stars);
  const validation =
    attackValue === undefined || starValue === undefined
      ? "Use whole numbers for attacks and stars, or leave them blank."
      : participationValidation(attackValue, starValue, draft.notes);

  useEffect(() => {
    if (changed || !stale) return;
    const latest = values(account);
    setDraft(latest);
    setBase({
      ...latest,
      revision: account.revision,
      publicationVersion,
      rosterToken: account.roster_token,
      sourceCheckedAt: account.source_checked_at ?? null,
    });
  }, [account, publicationVersion, changed, stale]);
  useEffect(() => {
    onDirty(account.tag, changed || busy);
    return () => onDirty(account.tag, false);
  }, [account.tag, changed, busy, onDirty]);
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    else if (!open && dialog.current?.open) dialog.current.close();
  }, [open]);

  const useLatest = () => {
    const latest = values(account);
    setDraft(latest);
    setBase({
      ...latest,
      revision: account.revision,
      publicationVersion,
      rosterToken: account.roster_token,
      sourceCheckedAt: account.source_checked_at ?? null,
    });
    setError("");
  };
  const closeEditor = () => {
    if (busy) return;
    if (
      changed &&
      !window.confirm(`Discard unsaved results for ${account.player_name}?`)
    )
      return;
    if (changed) useLatest();
    dialog.current?.close();
  };
  const save = async () => {
    if (
      readonly ||
      locked ||
      busy ||
      pending.current ||
      !changed ||
      stale ||
      validation ||
      attackValue === undefined ||
      starValue === undefined
    )
      return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const saved = await onSave(
        { ...account, roster_token: base.rosterToken },
        base.revision,
        base.publicationVersion,
        base.sourceCheckedAt,
        attackValue,
        starValue,
        draft.notes,
      );
      const latest = values(saved);
      setDraft(latest);
      setBase({
        ...latest,
        revision: saved.revision,
        publicationVersion,
        rosterToken: saved.roster_token,
        sourceCheckedAt: saved.source_checked_at ?? null,
      });
      dialog.current?.close();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const reset = async () => {
    if (
      readonly ||
      locked ||
      busy ||
      pending.current ||
      changed ||
      stale ||
      !canReset
    )
      return;
    const partial = !account.source_complete
      ? " These source results are partial and may change."
      : "";
    if (
      !window.confirm(
        `Replace manual attack and star overrides for ${account.player_name} with synced values? Staff notes stay saved.${partial}`,
      )
    )
      return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const saved = await onReset(account);
      const latest = values(saved);
      setDraft(latest);
      setBase({
        ...latest,
        revision: saved.revision,
        publicationVersion,
        rosterToken: saved.roster_token,
        sourceCheckedAt: saved.source_checked_at ?? null,
      });
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };

  return (
    <article
      className={`participation-row${account.roster_changed ? " participation-row-changed" : ""}`}
    >
      <div className="participation-identity">
        <strong>{account.player_name}</strong>
        <small>
          {account.tag} · TH {account.town_hall ?? "—"} ·{" "}
          {account.assigned_clan_name ||
            account.assigned_clan_tag ||
            "Awaiting placement"}
        </small>
      </div>
      <div className="participation-values">
        <span>
          <strong>{account.attacks ?? "—"}</strong>
          <small>Attacks</small>
        </span>
        <span>
          <strong>{account.stars ?? "—"}</strong>
          <small>Stars</small>
        </span>
      </div>
      <div className="participation-state">
        <strong>
          {account.roster_changed
            ? "Assignment changed"
            : syncStatusLabel(account.source_status)}
        </strong>
        {hasOverride && !account.roster_changed && (
          <small>Staff correction</small>
        )}
        {account.source_warning && <small>{account.source_warning}</small>}
      </div>
      <button
        ref={opener}
        type="button"
        className="participation-row-action"
        disabled={locked}
        onClick={onOpen}
      >
        Details
        <span className="participation-visually-hidden">
          {" "}
          for {account.player_name}
        </span>
      </button>

      <dialog
        ref={dialog}
        className="participation-dialog"
        aria-labelledby={titleId}
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const focusable = Array.from(
            dialog.current?.querySelectorAll<HTMLElement>(
              'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], summary, [tabindex]:not([tabindex="-1"])',
            ) || [],
          ).filter((element) => element.getClientRects().length > 0);
          if (!focusable.length) {
            event.preventDefault();
            return;
          }
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          const active = document.activeElement;
          if (
            event.shiftKey &&
            (active === first || !dialog.current?.contains(active))
          ) {
            event.preventDefault();
            last.focus();
          } else if (
            !event.shiftKey &&
            (active === last || !dialog.current?.contains(active))
          ) {
            event.preventDefault();
            first.focus();
          }
        }}
        onCancel={(event) => {
          if (
            busy ||
            (changed &&
              !window.confirm(
                `Discard unsaved results for ${account.player_name}?`,
              ))
          )
            event.preventDefault();
          else if (changed) useLatest();
        }}
        onClose={() => {
          onClose();
          requestAnimationFrame(
            () =>
              opener.current?.isConnected &&
              opener.current.focus({ preventScroll: true }),
          );
        }}
      >
        <div className="participation-dialog-head">
          <div>
            <h2 id={titleId}>{account.player_name}</h2>
            <small>
              {account.tag} ·{" "}
              {account.pool === "main" ? "Main CWL" : "Lazy CWL"} ·{" "}
              {account.assigned_clan_name ||
                account.assigned_clan_tag ||
                "Unassigned"}
            </small>
          </div>
          <button type="button" disabled={busy} onClick={closeEditor}>
            Close
          </button>
        </div>
        {open && (
          <DiscordIdentity
            userId={account.user_id}
            resolvedMember={people.members[account.user_id || ""] || null}
            resolving={people.loading}
          />
        )}
        {account.roster_changed && (
          <div className="notice error" role="alert">
            Saved results belong to a previous assignment.{" "}
            {account.assigned_clan_tag
              ? "Refresh Clash results, then use synced values to replace old corrections."
              : "Assign this account to a CWL clan, then refresh Clash results."}
          </div>
        )}
        {account.previous_results && (
          <details className="participation-previous">
            <summary>Previous assignment and corrections</summary>
            <p>
              {account.previous_results.pool === "main"
                ? "Main CWL"
                : "Lazy CWL"}{" "}
              ·{" "}
              {account.previous_results.assigned_clan_name ||
                account.previous_results.assigned_clan_tag ||
                "Unassigned"}{" "}
              · {account.previous_results.attacks ?? "—"} attacks ·{" "}
              {account.previous_results.stars ?? "—"} stars
            </p>
          </details>
        )}
        <div className="participation-dialog-summary">
          <div>
            <strong>{account.attacks ?? "—"}</strong>
            <span>Recorded attacks</span>
          </div>
          <div>
            <strong>{account.stars ?? "—"}</strong>
            <span>Recorded stars</span>
          </div>
          <div>
            <strong>{syncStatusLabel(account.source_status)}</strong>
            <span>Clash source</span>
          </div>
        </div>
        <details className="participation-source">
          <summary>Synced source and corrections</summary>
          <p>
            Synced: {account.source_attacks ?? "Unrecorded"} attacks ·{" "}
            {account.source_stars ?? "Unrecorded"} stars
          </p>
          <p>
            {syncStatusLabel(account.source_status)}
            {hasSource
              ? account.source_complete
                ? " · Final results"
                : " · Partial results"
              : ""}
            {account.source_checked_at
              ? ` · Checked ${dateText(account.source_checked_at)}`
              : ""}
          </p>
          {account.source_warning && (
            <p className="participation-error">{account.source_warning}</p>
          )}
          {!account.source_complete && hasSource && (
            <p className="participation-error">
              Source observations are incomplete; synced totals may change.
            </p>
          )}
          {hasOverride && (
            <p>
              Manual correction in use
              {account.attacks_override && account.stars_override
                ? " for attacks and stars"
                : account.attacks_override
                  ? " for attacks"
                  : " for stars"}
              .
            </p>
          )}
          {hasOverride && (
            <button
              type="button"
              disabled={
                readonly || locked || busy || changed || stale || !canReset
              }
              onClick={() => void reset()}
            >
              Use synced results
            </button>
          )}
          {hasOverride && !hasSource && (
            <p>
              Synced values are unavailable, so the correction cannot be reset
              yet.
            </p>
          )}
        </details>
        <div className="participation-fields">
          <label>
            Attacks
            <input
              type="number"
              min="0"
              max="7"
              step="1"
              inputMode="numeric"
              value={draft.attacks}
              disabled={readonly || locked || busy || !!account.roster_changed}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  attacks: event.target.value,
                }))
              }
              placeholder="Unrecorded"
            />
          </label>
          <label>
            Stars
            <input
              type="number"
              min="0"
              max="21"
              step="1"
              inputMode="numeric"
              value={draft.stars}
              disabled={readonly || locked || busy || !!account.roster_changed}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  stars: event.target.value,
                }))
              }
              placeholder="Unrecorded"
            />
          </label>
        </div>
        <label className="participation-notes">
          Staff notes
          <textarea
            rows={3}
            maxLength={2000}
            value={draft.notes}
            disabled={readonly || locked || busy || !!account.roster_changed}
            onChange={(event) =>
              setDraft((current) => ({ ...current, notes: event.target.value }))
            }
            placeholder="Optional note about this correction"
          />
        </label>
        {stale && changed && (
          <div className="notice error" role="alert">
            This record or assignment changed while you were editing. Your entry
            remains here; review the latest values before saving.
            <button type="button" disabled={busy} onClick={useLatest}>
              Discard entry and use latest
            </button>
          </div>
        )}
        {validation && changed && (
          <p role="alert" className="participation-error">
            {validation}
          </p>
        )}
        {error && (
          <p role="alert" className="participation-error">
            {error}
          </p>
        )}
        {account.updated_at && (
          <p className="participation-saved-at">
            Last saved {dateText(account.updated_at)}
            {account.updated_by && (
              <>
                {" "}
                by{" "}
                <DiscordIdentity
                  userId={account.updated_by}
                  resolvedMember={people.members[account.updated_by] || null}
                  resolving={people.loading}
                  variant="compact"
                />
              </>
            )}
          </p>
        )}
        <div className="participation-dialog-actions">
          <button type="button" disabled={busy} onClick={closeEditor}>
            Cancel
          </button>
          <button
            type="button"
            className="primary"
            disabled={
              readonly ||
              locked ||
              busy ||
              !!account.roster_changed ||
              !changed ||
              stale ||
              !!validation
            }
            onClick={() => void save()}
          >
            {busy ? "Saving…" : "Save results"}
          </button>
        </div>
      </dialog>
    </article>
  );
}
