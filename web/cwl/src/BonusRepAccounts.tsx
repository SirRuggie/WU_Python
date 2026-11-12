import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import BonusClanRepFinder from "./BonusClanRepFinder";
import DiscordIdentity, { type DiscordProfile } from "./DiscordIdentity";
import type { MemberOption } from "./MemberPicker";
import TownHallIcon from "./TownHallIcon";
import type { RepAccount } from "./bonusRaffle";
import "./BonusRepAccounts.css";

export const REP_NOTE_MAX = 40;

type Mutate = (
  method: "POST" | "PATCH" | "DELETE",
  body: Record<string, unknown>,
  notice: string,
) => Promise<boolean>;

type Props = {
  seasonId: string;
  accounts: RepAccount[];
  disabled: boolean;
  onDirty: (dirty: boolean) => void;
  onConfirm: (message: string, action: string) => Promise<boolean>;
  onMutate: Mutate;
};

const NOT_LINKED = "";

/** Group rows by linked Discord user, the same as Build roster; unlinked last. */
export function repGroups(accounts: RepAccount[]) {
  const groups = new Map<string, RepAccount[]>();
  for (const account of accounts)
    groups.set(account.user_id || NOT_LINKED, [
      ...(groups.get(account.user_id || NOT_LINKED) || []),
      account,
    ]);
  return [...groups.entries()].sort(
    ([a], [b]) => Number(a === NOT_LINKED) - Number(b === NOT_LINKED),
  );
}

/** FWA Rep accounts for Lazy draw odds; one section of the Settings sheet. */
export default function BonusRepAccounts({
  seasonId,
  accounts,
  disabled,
  onDirty,
  onConfirm,
  onMutate,
}: Props) {
  const [tag, setTag] = useState("");
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editNote, setEditNote] = useState("");
  const [profiles, setProfiles] = useState<Record<string, DiscordProfile>>({});
  const [resolving, setResolving] = useState(false);
  const [finderDirty, setFinderDirty] = useState(false);
  const listed = useMemo(
    () => new Set(accounts.map((row) => row.tag)),
    [accounts],
  );
  const groups = useMemo(() => repGroups(accounts), [accounts]);
  const ids = useMemo(
    () =>
      groups
        .map(([id]) => id)
        .filter((id) => /^[1-9]\d{14,21}$/.test(id))
        .slice(0, 100)
        .join(","),
    [groups],
  );
  const editRow = accounts.find((row) => row.tag === editing);
  const dirty =
    finderDirty ||
    !!tag.trim() ||
    !!note.trim() ||
    (!!editRow && editNote.trim() !== editRow.note);
  useEffect(() => {
    onDirty(dirty);
  }, [dirty, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);
  useEffect(() => {
    let active = true;
    if (!ids) return;
    setResolving(true);
    api<{ options: MemberOption[] }>(
      `/staff-signup-members?ids=${encodeURIComponent(ids)}`,
    )
      .then((data) => {
        if (active)
          setProfiles(
            Object.fromEntries(data.options.map((row) => [row.id, row])),
          );
      })
      // A failed lookup keeps the rows grouped by Discord ID.
      .catch(() => undefined)
      .finally(() => {
        if (active) setResolving(false);
      });
    return () => {
      active = false;
    };
  }, [ids]);

  const add = async () => {
    if (disabled || !tag.trim()) return;
    if (
      await onMutate(
        "POST",
        { tag: tag.trim(), note: note.trim() },
        "FWA Rep account added. Check the draw again before saving.",
      )
    ) {
      setTag("");
      setNote("");
    }
  };
  const saveNote = async (row: RepAccount) => {
    if (disabled) return;
    if (
      await onMutate(
        "PATCH",
        { tag: row.tag, note: editNote.trim(), rep_revision: row.revision },
        "Note saved.",
      )
    )
      setEditing(null);
  };
  const remove = async (row: RepAccount) => {
    if (
      disabled ||
      !(await onConfirm(
        `Remove ${row.player_name} (${row.tag})? It gets 1 chance in Lazy draws.`,
        "Remove account",
      ))
    )
      return;
    if (
      (await onMutate(
        "DELETE",
        { tag: row.tag, rep_revision: row.revision },
        "FWA Rep account removed. Check the draw again before saving.",
      )) &&
      editing === row.tag
    )
      setEditing(null);
  };

  return (
    <section
      className="results-settings-section rep-accounts"
      aria-label="FWA Rep accounts"
    >
      <h3>FWA Rep accounts</h3>
      <p>Only these accounts get 2 chances in Lazy draws, in every season.</p>
      <BonusClanRepFinder
        seasonId={seasonId}
        listed={listed}
        noteMax={REP_NOTE_MAX}
        disabled={disabled}
        onDirty={setFinderDirty}
        onAdd={(value, text) =>
          onMutate(
            "POST",
            { tag: value, note: text },
            "FWA Rep account added. Check the draw again before saving.",
          )
        }
      />
      <h4 className="rep-accounts-subhead">Or add by player tag</h4>
      <form
        className="rep-accounts-add"
        onSubmit={(event) => {
          event.preventDefault();
          void add();
        }}
      >
        <label>
          Player tag
          <input
            name="rep-tag"
            autoComplete="off"
            spellCheck={false}
            maxLength={20}
            value={tag}
            disabled={disabled}
            onChange={(event) => setTag(event.target.value)}
          />
        </label>
        <label>
          Note (optional)
          <input
            name="rep-note"
            autoComplete="off"
            maxLength={REP_NOTE_MAX}
            value={note}
            disabled={disabled}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <button type="submit" disabled={disabled || !tag.trim()}>
          Add account
        </button>
      </form>
      {accounts.length === 0 ? (
        <p className="rep-accounts-empty">
          No FWA Rep accounts. Every Lazy account has 1 chance.
        </p>
      ) : (
        <div className="rep-accounts-list">
          {groups.map(([userId, rows]) => (
            <div key={userId || "not-linked"} className="rep-accounts-group">
              <header className="roster-member-heading">
                {userId ? (
                  <DiscordIdentity
                    userId={userId}
                    resolvedMember={profiles[userId] || null}
                    resolving={resolving}
                    contact={false}
                    username={false}
                  />
                ) : (
                  <strong>Not linked</strong>
                )}
                <small>
                  {rows.length} account{rows.length === 1 ? "" : "s"}
                </small>
              </header>
              <ul>
                {rows.map((row) => (
                  <li key={row.tag} className="rep-account-row">
                    <TownHallIcon level={row.town_hall} />
                    <div className="rep-account-main">
                      <strong>{row.player_name}</strong>
                      <small>
                        {row.tag} · TH{row.town_hall ?? "—"}
                      </small>
                      {editing === row.tag ? (
                        <form
                          className="rep-account-note-edit"
                          onSubmit={(event) => {
                            event.preventDefault();
                            void saveNote(row);
                          }}
                        >
                          <label>
                            Note
                            <input
                              name="rep-edit-note"
                              autoComplete="off"
                              maxLength={REP_NOTE_MAX}
                              value={editNote}
                              disabled={disabled}
                              autoFocus
                              onChange={(event) =>
                                setEditNote(event.target.value)
                              }
                            />
                          </label>
                          <div className="rep-account-actions">
                            <button
                              type="submit"
                              disabled={
                                disabled || editNote.trim() === row.note
                              }
                            >
                              Save note
                            </button>
                            <button
                              type="button"
                              disabled={disabled}
                              onClick={() => setEditing(null)}
                            >
                              Cancel
                            </button>
                          </div>
                        </form>
                      ) : (
                        row.note && (
                          <span className="rep-account-note">{row.note}</span>
                        )
                      )}
                    </div>
                    {editing !== row.tag && (
                      <div className="rep-account-actions">
                        <button
                          type="button"
                          disabled={disabled || (!!editing && dirty)}
                          aria-label={`Edit note for ${row.player_name}`}
                          onClick={() => {
                            setEditing(row.tag);
                            setEditNote(row.note);
                          }}
                        >
                          Edit note
                        </button>
                        <button
                          type="button"
                          disabled={disabled}
                          aria-label={`Remove ${row.player_name}`}
                          onClick={() => void remove(row)}
                        >
                          Remove
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
