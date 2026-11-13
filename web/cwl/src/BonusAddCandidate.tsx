import type { RefObject } from "react";

type Lookup = {
  account: {
    tag: string;
    name: string;
    town_hall: number;
    current_clan_name?: string | null;
  };
};

type Props = {
  open: boolean;
  disabled: boolean;
  busy: boolean;
  lookingUp: boolean;
  canManage: boolean;
  error: string;
  tag: string;
  reason: string;
  lookup: Lookup | null;
  openerRef: RefObject<HTMLButtonElement | null>;
  tagInputRef: RefObject<HTMLInputElement | null>;
  onToggle: () => void;
  onTag: (value: string) => void;
  onReason: (value: string) => void;
  onFind: () => void;
  onCancel: () => void;
  onAdd: () => void;
};

/** Add player by tag: the toggle button and its editor (Lazy only). */
export default function BonusAddCandidate({
  open,
  disabled,
  busy,
  lookingUp,
  canManage,
  error,
  tag,
  reason,
  lookup,
  openerRef,
  tagInputRef,
  onToggle,
  onTag,
  onReason,
  onFind,
  onCancel,
  onAdd,
}: Props) {
  return (
    <>
      <div className="bonus-candidates-heading">
        <button
          ref={openerRef}
          type="button"
          disabled={disabled}
          onClick={onToggle}
        >
          Add player by tag
        </button>
      </div>
      {open && (
        <section
          className="bonus-add-candidate"
          aria-label="Add bonus candidate"
        >
          <p>
            Add an account directly to this clan’s candidate pool. This does not
            change its signup or roster placement.
          </p>
          <div className="bonus-lookup">
            <label>
              Player tag
              <input
                ref={tagInputRef}
                name="player-tag"
                autoComplete="off"
                spellCheck={false}
                autoCapitalize="characters"
                inputMode="text"
                value={tag}
                maxLength={20}
                disabled={busy || lookingUp}
                placeholder="#2PP0JCCL…"
                onChange={(event) => onTag(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={!tag.trim() || busy || lookingUp}
              onClick={onFind}
            >
              {lookingUp ? "Looking up…" : "Find player"}
            </button>
          </div>
          {lookup && (
            <p>
              <strong>{lookup.account.name}</strong> · {lookup.account.tag} · TH{" "}
              {lookup.account.town_hall}
              {lookup.account.current_clan_name
                ? ` · ${lookup.account.current_clan_name}`
                : ""}
            </p>
          )}
          <label>
            Reason for addition
            <textarea
              name="candidate-reason"
              autoComplete="off"
              value={reason}
              maxLength={500}
              disabled={busy}
              onChange={(event) => onReason(event.target.value)}
              placeholder="Why this player enters this clan’s draw…"
            />
          </label>
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}
          <div className="bonus-editor-actions">
            <button type="button" disabled={busy} onClick={onCancel}>
              Cancel
            </button>
            <button
              type="button"
              className="primary"
              disabled={!canManage || busy || !lookup || !reason.trim()}
              onClick={onAdd}
            >
              Add candidate
            </button>
          </div>
        </section>
      )}
    </>
  );
}
