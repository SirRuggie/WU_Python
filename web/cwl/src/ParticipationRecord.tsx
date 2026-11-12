import PriorWinner from "./PriorWinner";
import AccountCard from "./AccountCard";
import CardTally from "./CardTally";
import useConfirmDialog from "./useConfirmDialog";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Flag, Info } from "lucide-react";
import DiscordIdentity from "./DiscordIdentity";
import useDiscordIdentities from "./useDiscordIdentities";
import { StatusPill } from "./rosterUi/primitives";
import ActionMenu, { type ActionMenuItem } from "./rosterUi/ActionMenu";
import { discordMessageItem } from "./RosterAccountMenu";
import InfractionsSection, {
  noInfractionsDraft,
  type InfractionsDraft,
} from "./InfractionsSection";
import type { Infractions } from "./useInfractions";
import {
  countText,
  outcomeLabels,
  outcomeTone,
  participationOutcome,
  resultDateText,
} from "./participationOutcome";
import {
  canUseSyncedResults,
  participationStatus,
  type ParticipationAccount,
} from "./participation";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Could not save notes.";
const dateText = resultDateText;

type Props = {
  account: ParticipationAccount;
  /** Saved Main minimum; Main shows no outcome without one. */
  mainMinimum?: number | null;
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
    notes: string,
  ) => Promise<ParticipationAccount>;
  onReset: (account: ParticipationAccount) => Promise<ParticipationAccount>;
  onDirty: (tag: string, dirty: boolean) => void;
  /** Opens Strikes on this player; absent without strike access. */
  onAddStrike?: (tag: string) => void;
  /** Lazy infractions; absent without bonus access. */
  infractions?: Infractions;
};

/** Card ⋯ menu items. Add new actions to this list. */
export function participationMenuItems({
  account,
  onDetails,
  onAddStrike,
}: {
  account: ParticipationAccount;
  onDetails: (trigger: HTMLElement) => void;
  onAddStrike?: (tag: string) => void;
}): ActionMenuItem[] {
  return [
    discordMessageItem(account.user_id),
    { id: "details", label: "Details", icon: Info, onAction: onDetails },
    // Staff review first: this only opens Strikes; nothing is written here.
    ...(account.did_not_join && onAddStrike
      ? [
          {
            id: "add-strike",
            label: "Add strike",
            icon: Flag,
            separatorBefore: true,
            onAction: () => onAddStrike(account.tag),
          },
        ]
      : []),
  ];
}

export default function ParticipationRecord({
  account,
  mainMinimum = null,
  publicationVersion,
  readonly,
  locked,
  open,
  onOpen,
  onClose,
  onSave,
  onReset,
  onDirty,
  onAddStrike,
  infractions,
}: Props) {
  const { confirm, dialog: confirmation } = useConfirmDialog(
    `${account.tag}:${account.revision}:${publicationVersion}:${readonly}:${locked}:${open}`,
  );
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  // Focus returns to whichever control opened Details: the card or ⋯.
  const returnFocus = useRef<HTMLElement | null>(null);
  const openFrom = (element: HTMLElement | null) => {
    returnFocus.current = element;
    onOpen();
  };
  const people = useDiscordIdentities(
    [account.user_id, account.updated_by],
    open,
  );
  const [draft, setDraft] = useState(account.notes);
  const [base, setBase] = useState(() => ({
    notes: account.notes,
    revision: account.revision,
    publicationVersion,
    rosterToken: account.roster_token,
    sourceCheckedAt: account.source_checked_at ?? null,
  }));
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState("");
  const changed = draft !== base.notes;
  // Infractions have their own editor; the footer Save and the close guard cover both.
  const showInfractions =
    !!infractions && account.pool === "lazy" && !!account.assigned_clan_tag;
  const [infractionsDraft, setInfractionsDraft] = useState(noInfractionsDraft);
  const [infractionsError, setInfractionsError] = useState("");
  const [infractionsNotice, setInfractionsNotice] = useState("");
  const [infractionsEpoch, setInfractionsEpoch] = useState(0);
  const onInfractionsDraft = useCallback(
    (next: InfractionsDraft) =>
      setInfractionsDraft((current) =>
        current.dirty === next.dirty &&
        current.flags === next.flags &&
        current.reason === next.reason
          ? current
          : next,
      ),
    [],
  );
  const infractionsLocked = showInfractions
    ? infractions?.lock(account.assigned_clan_tag)
    : null;
  const canSaveInfractions =
    showInfractions &&
    !infractionsLocked &&
    infractionsDraft.dirty &&
    !(infractionsDraft.reason && !infractionsDraft.reason.trim());
  const infractionsData = infractions?.data;
  const infractionsLoad = infractions?.state;
  useEffect(() => {
    if (
      open &&
      showInfractions &&
      !infractionsData &&
      infractionsLoad === "idle"
    )
      infractions?.load();
  }, [open, showInfractions, infractionsData, infractionsLoad]);
  const stale =
    account.roster_token !== base.rosterToken ||
    account.revision !== base.revision ||
    publicationVersion !== base.publicationVersion ||
    (account.source_checked_at ?? null) !== base.sourceCheckedAt ||
    account.notes !== base.notes;
  const hasOverride = !!(
    account.attacks_override ||
    account.stars_override ||
    account.roster_changed
  );
  const hasSource =
    (account.source_attacks !== null && account.source_attacks !== undefined) ||
    (account.source_stars !== null && account.source_stars !== undefined);
  // Results are read only; reconciling a changed assignment is the one reset.
  const canReset = !!account.roster_changed && canUseSyncedResults(account);
  const outcome = participationOutcome(account, mainMinimum);
  const status = participationStatus(account);

  const latestBase = (row: ParticipationAccount) => ({
    notes: row.notes,
    revision: row.revision,
    publicationVersion,
    rosterToken: row.roster_token,
    sourceCheckedAt: row.source_checked_at ?? null,
  });
  useEffect(() => {
    if (changed || !stale) return;
    setDraft(account.notes);
    setBase(latestBase(account));
  }, [account, publicationVersion, changed, stale]);
  useEffect(() => {
    onDirty(account.tag, changed || busy || infractionsDraft.dirty);
    return () => onDirty(account.tag, false);
  }, [account.tag, changed, busy, infractionsDraft.dirty, onDirty]);
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    else if (!open && dialog.current?.open) dialog.current.close();
  }, [open]);

  const useLatest = () => {
    setDraft(account.notes);
    setBase(latestBase(account));
    setError("");
  };
  const closeEditor = async () => {
    if (busy) return;
    const unsaved = changed || infractionsDraft.dirty;
    if (
      unsaved &&
      !(await confirm(
        changed && !infractionsDraft.dirty
          ? `Discard unsaved notes for ${account.player_name}?`
          : `Discard unsaved changes for ${account.player_name}?`,
        changed && !infractionsDraft.dirty
          ? "Discard notes"
          : "Discard changes",
      ))
    )
      return;
    if (changed) useLatest();
    if (infractionsDraft.dirty) setInfractionsEpoch((value) => value + 1);
    setInfractionsError("");
    setInfractionsNotice("");
    dialog.current?.close();
  };
  const canSaveNotes =
    !readonly &&
    !locked &&
    !!changed &&
    !stale &&
    !account.roster_changed &&
    draft.length <= 2000;
  // One Save writes what changed: notes first, then infractions.
  const save = async () => {
    if (busy || pending.current || !(canSaveNotes || canSaveInfractions))
      return;
    pending.current = true;
    setBusy(true);
    setError("");
    setInfractionsError("");
    setInfractionsNotice("");
    let failed = false;
    if (canSaveNotes) {
      try {
        const saved = await onSave(
          { ...account, roster_token: base.rosterToken },
          base.revision,
          base.publicationVersion,
          base.sourceCheckedAt,
          draft,
        );
        setDraft(saved.notes);
        setBase(latestBase(saved));
      } catch (cause) {
        failed = true;
        setError(errorText(cause));
      }
    }
    let infractionsSaved = false;
    if (canSaveInfractions && infractions) {
      try {
        await infractions.save(
          account.tag,
          infractionsDraft.flags,
          infractionsDraft.reason.trim(),
        );
        infractionsSaved = true;
        setInfractionsNotice(
          `Infractions saved · ${account.assigned_clan_name || account.assigned_clan_tag} eligibility updated.`,
        );
      } catch (cause) {
        failed = true;
        setInfractionsError(
          cause instanceof Error
            ? cause.message
            : "Infractions could not be saved. Try again.",
        );
      }
    }
    pending.current = false;
    setBusy(false);
    // A saved infractions change keeps the sheet open to show what changed.
    if (!failed && !infractionsSaved) dialog.current?.close();
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
      ? " These CWL totals may change while wars continue."
      : "";
    if (
      !(await confirm(
        `Use the Clash results for ${account.player_name}'s new assignment? Staff notes stay saved.${partial}`,
        "Use synced results",
      ))
    )
      return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const saved = await onReset(account);
      setDraft(saved.notes);
      setBase(latestBase(saved));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };

  return (
    <AccountCard
      className={`participation-row account-card-plain${account.roster_changed ? " participation-row-changed" : ""}`}
      thLevel={account.town_hall}
      name={
        <button
          ref={opener}
          type="button"
          className="account-card-open"
          aria-label={`Details for ${account.player_name}`}
          disabled={locked}
          onClick={() => openFrom(opener.current)}
        >
          {account.player_name}
        </button>
      }
      meta={[
        <>TH {account.town_hall ?? "—"}</>,
        account.tag,
        <span className="participation-clan">
          {account.assigned_clan_name ||
            account.assigned_clan_tag ||
            "Unplaced"}
        </span>,
      ]}
      status={
        account.roster_changed
          ? { tone: "bad", content: "Assignment changed" }
          : outcome
            ? {
                tone: "neutral",
                content: (
                  <StatusPill
                    tone={outcomeTone(outcome)}
                    className="participation-outcome"
                  >
                    {outcomeLabels[outcome]}
                  </StatusPill>
                ),
              }
            : undefined
      }
      flags={[
        <PriorWinner account={account} />,
        hasOverride && !account.roster_changed ? "Staff correction" : null,
      ]}
      values={
        <CardTally
          attacks={account.attacks ?? "—"}
          stars={account.stars ?? "—"}
          tone={outcome ? outcomeTone(outcome) : null}
        />
      }
      action={
        <ActionMenu
          name={account.player_name}
          disabled={locked}
          items={participationMenuItems({
            account,
            onDetails: openFrom,
            onAddStrike,
          })}
        />
      }
    >
      {confirmation}
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
          event.preventDefault();
          void closeEditor();
        }}
        onClose={() => {
          onClose();
          const target = returnFocus.current?.isConnected
            ? returnFocus.current
            : opener.current;
          returnFocus.current = null;
          requestAnimationFrame(
            () => target?.isConnected && target.focus({ preventScroll: true }),
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
                "Unplaced"}
            </small>
          </div>
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
              ? "Refresh the Clash results, then use them for the new assignment."
              : "Assign this account to a CWL clan, then refresh Clash results."}
            {canReset && (
              <button
                type="button"
                disabled={readonly || locked || busy || changed || stale}
                onClick={() => void reset()}
              >
                Use synced results
              </button>
            )}
          </div>
        )}
        <PriorWinner account={account} details />
        <div className="participation-dialog-summary">
          <div>
            <strong>{account.attacks ?? "—"}</strong>
            <span>Attacks</span>
          </div>
          <div>
            <strong>{account.stars ?? "—"}</strong>
            <span>Stars</span>
          </div>
          <div>
            <strong>{status.label}</strong>
            <span>Clash capture</span>
          </div>
        </div>
        <p className="participation-dialog-capture">
          {hasSource
            ? account.source_complete
              ? "Final results from Clash"
              : "Results so far from Clash"
            : "No results captured from Clash"}
          {account.source_checked_at
            ? ` · Checked ${dateText(account.source_checked_at)}`
            : ""}
          {hasOverride && !account.roster_changed
            ? " · Staff correction in use"
            : ""}
        </p>
        {status.warning && (
          <p className="participation-error">{status.warning}</p>
        )}
        {account.previous_results && (
          <details className="participation-previous">
            <summary>Previous assignment</summary>
            <p>
              {account.previous_results.pool === "main"
                ? "Main CWL"
                : "Lazy CWL"}{" "}
              ·{" "}
              {account.previous_results.assigned_clan_name ||
                account.previous_results.assigned_clan_tag ||
                "Unplaced"}{" "}
              ·{" "}
              {account.previous_results.attacks === null
                ? "— attacks"
                : countText(account.previous_results.attacks, "attack")}{" "}
              ·{" "}
              {account.previous_results.stars === null
                ? "— stars"
                : countText(account.previous_results.stars, "star")}
            </p>
          </details>
        )}
        <label className="participation-notes">
          Staff notes
          <textarea
            name="notes"
            autoComplete="off"
            rows={3}
            maxLength={2000}
            value={draft}
            disabled={readonly || locked || busy || !!account.roster_changed}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Optional note"
          />
        </label>
        {showInfractions && infractions && (
          <InfractionsSection
            tag={account.tag}
            clanTag={account.assigned_clan_tag!}
            infractions={infractions}
            resetKey={infractionsEpoch}
            busy={busy}
            error={infractionsError}
            notice={infractionsNotice}
            onDraft={onInfractionsDraft}
          />
        )}
        {stale && changed && (
          <div className="notice error" role="alert">
            This record or assignment changed while you were editing. Your notes
            remain here; review the latest values before saving.
            <button type="button" disabled={busy} onClick={useLatest}>
              Discard notes and use latest
            </button>
          </div>
        )}
        {error && (
          <p role="alert" className="participation-error">
            Notes not saved · {error}
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
            disabled={busy || !(canSaveNotes || canSaveInfractions)}
            onClick={() => void save()}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </dialog>
    </AccountCard>
  );
}
