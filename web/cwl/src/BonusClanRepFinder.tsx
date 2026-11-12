import { useEffect, useState } from "react";
import { api } from "./api";
import SearchPicker, { type PickerOption } from "./SearchPicker";
import TownHallIcon from "./TownHallIcon";

type ClanRep = {
  id: string;
  display_name: string;
  username: string;
  avatar_url?: string | null;
};
type LinkedAccount = { tag: string; name: string; town_hall: number | null };

type Props = {
  seasonId: string;
  listed: Set<string>;
  noteMax: number;
  disabled: boolean;
  onDirty: (dirty: boolean) => void;
  onAdd: (tag: string, note: string) => Promise<boolean>;
};

const errorText = (cause: unknown, fallback: string) =>
  cause instanceof Error ? cause.message : fallback;

/** Find FWA Clan Rep role members and add their linked accounts for x2 odds. */
export default function BonusClanRepFinder({
  seasonId,
  listed,
  noteMax,
  disabled,
  onDirty,
  onAdd,
}: Props) {
  const base = `/seasons/${encodeURIComponent(seasonId)}`;
  const [members, setMembers] = useState<ClanRep[] | null>(null);
  const [membersError, setMembersError] = useState("");
  const [membersRetry, setMembersRetry] = useState(0);
  const [userId, setUserId] = useState("");
  const [accounts, setAccounts] = useState<LinkedAccount[] | null>(null);
  const [accountsError, setAccountsError] = useState("");
  const [accountsRetry, setAccountsRetry] = useState(0);
  const [note, setNote] = useState("");
  useEffect(() => {
    onDirty(!!note.trim());
  }, [note, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);
  useEffect(() => {
    let active = true;
    setMembersError("");
    api<{ members: ClanRep[] }>(`${base}/bonus-raffle/clan-rep-members`)
      .then((data) => {
        if (active) setMembers(data.members);
      })
      .catch((cause) => {
        if (active)
          setMembersError(
            errorText(cause, "Clan Reps could not be loaded. Try again."),
          );
      });
    return () => {
      active = false;
    };
  }, [base, membersRetry]);
  useEffect(() => {
    let active = true;
    setAccounts(null);
    setAccountsError("");
    if (!userId) return;
    api<{ accounts: LinkedAccount[] }>(
      `${base}/staff-signups/accounts?user_id=${encodeURIComponent(userId)}`,
    )
      .then((data) => {
        if (active) setAccounts(data.accounts);
      })
      .catch((cause) => {
        if (active)
          setAccountsError(
            errorText(cause, "Linked accounts could not be loaded."),
          );
      });
    return () => {
      active = false;
    };
  }, [base, userId, accountsRetry]);

  const options: PickerOption[] = (members || []).map((member) => ({
    value: member.id,
    label: member.display_name,
    detail:
      member.username && member.username !== member.display_name
        ? member.username
        : undefined,
  }));
  const add = async (account: LinkedAccount) => {
    if (disabled) return;
    if (await onAdd(account.tag, note.trim())) setNote("");
  };

  return (
    <div className="rep-finder" role="group" aria-label="Find Clan Rep">
      {membersError ? (
        <p role="alert">
          {membersError}{" "}
          <button
            type="button"
            onClick={() => setMembersRetry((value) => value + 1)}
          >
            Retry
          </button>
        </p>
      ) : members === null ? (
        <p role="status">Loading Clan Reps…</p>
      ) : (
        <SearchPicker
          label="Find Clan Rep (x2 odds)"
          value={userId}
          options={options}
          disabled={disabled}
          clearable
          placeholder="Select a Clan Rep…"
          searchPlaceholder="Name…"
          emptyText="No Clan Reps match."
          onChange={(value) => {
            setUserId(value);
            // The note box belongs to the selected member; never keep a hidden note.
            setNote("");
          }}
        />
      )}
      {userId && (
        <>
          <label className="rep-finder-note">
            Note (optional)
            <input
              name="rep-finder-note"
              autoComplete="off"
              maxLength={noteMax}
              value={note}
              disabled={disabled}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          {accountsError ? (
            <p role="alert">
              {accountsError}{" "}
              <button
                type="button"
                onClick={() => setAccountsRetry((value) => value + 1)}
              >
                Retry
              </button>
            </p>
          ) : accounts === null ? (
            <p role="status">Loading linked accounts…</p>
          ) : accounts.length === 0 ? (
            <p>No linked accounts. Add the account by tag below.</p>
          ) : (
            <ul className="rep-finder-accounts">
              {accounts.map((account) => (
                <li key={account.tag} className="rep-account-row">
                  <TownHallIcon level={account.town_hall} />
                  <div className="rep-account-main">
                    <strong>{account.name}</strong>
                    <small>
                      {account.tag} · TH{account.town_hall ?? "—"}
                    </small>
                  </div>
                  {listed.has(account.tag) ? (
                    <span className="rep-finder-listed">x2 · Listed</span>
                  ) : (
                    <button
                      type="button"
                      disabled={disabled}
                      aria-label={`Add ${account.name} for x2`}
                      onClick={() => void add(account)}
                    >
                      Add for x2
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
