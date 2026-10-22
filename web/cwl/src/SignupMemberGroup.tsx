import { useRef, useState } from "react";
import { api, type Signup } from "./api";
import TownHallIcon from "./TownHallIcon";
import type { MemberOption } from "./MemberPicker";

type Props = {
  accounts: Signup[];
  name: string;
  identity?: MemberOption;
  groupKey?: string;
  seasonId: number;
  revision: number;
  editable: boolean;
  disabled: boolean;
  onActive: (active: boolean) => void;
  onBusy: (busy: boolean) => void;
  onChanged: (notice: string) => Promise<void>;
};
export default function SignupMemberGroup({
  accounts,
  name,
  identity,
  groupKey,
  seasonId,
  revision,
  editable,
  disabled,
  onActive,
  onBusy,
  onChanged,
}: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  const selectionTrigger = useRef<HTMLElement | null>(null);
  const [avatarFailed, setAvatarFailed] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [action, setAction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const uid = accounts[0].user_id || "";
  const chosen = accounts.filter((account) => selected.includes(account.tag));
  const affected = chosen.filter(
    (account) => action === "remove" || account.pool !== action,
  );
  const placed = affected.filter(
    (account) => account.has_staff_placement,
  ).length;
  function select(tags: string[]) {
    setSelected(tags);
    setAction("");
    setError("");
    onActive(tags.length > 0);
  }
  async function save() {
    if (busy || !action || !affected.length) return;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      const result = await api<{ count: number }>(
        `/seasons/${seasonId}/staff-signup-changes`,
        "POST",
        { revision, user_id: uid, tags: selected, action },
      );
      setSelected([]);
      setAction("");
      onActive(false);
      await onChanged(
        `${result.count} signup${result.count === 1 ? "" : "s"} ${action === "remove" ? "removed" : `changed to ${action === "main" ? "Main" : "Lazy"} CWL`}.`,
      );
      // The parent restores focus once the refreshed list has rendered.
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not save changes.",
      );
    } finally {
      setBusy(false);
      onBusy(false);
    }
  }
  function cancel() {
    select([]);
    requestAnimationFrame(() => {
      const target = selectionTrigger.current?.isConnected ? selectionTrigger.current : heading.current;
      target?.focus({ preventScroll: true });
    });
  }
  const avatarUrl = identity?.avatar_url?.startsWith("https://cdn.discordapp.com/")
    ? identity.avatar_url
    : null;
  return (
    <section className="signup-member-group" data-signup-group-key={groupKey} aria-label={`${name} signups`}>
      <header className="signup-member-heading">
        <div className="signup-member-identity">
          {avatarUrl && !avatarFailed ? (
            <img className="signup-member-avatar" src={avatarUrl} alt="" width={34} height={34} loading="lazy" onError={() => setAvatarFailed(true)} />
          ) : (
            <span className="signup-member-avatar signup-member-avatar-fallback" aria-hidden="true">{(identity?.display_name || name).slice(0, 1)}</span>
          )}
          <div>
            <h3 ref={heading} tabIndex={-1}>{name}</h3>
            <small>{identity?.username ? `@${identity.username} · ` : ""}{accounts.length} {accounts.length === 1 ? "account" : "accounts"}{uid ? ` · ${uid}` : ""}</small>
          </div>
        </div>
        {/^[0-9]{15,22}$/.test(uid) && (
          <a
            className="button"
            href={`https://discord.com/users/${uid}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Message ↗
          </a>
        )}
      </header>
      {editable && accounts.length > 1 && (
        <label className="signup-select-all">
          <input
            type="checkbox"
            checked={selected.length === accounts.length}
            disabled={disabled || busy}
            ref={(node) => {
              if (node)
                node.indeterminate =
                  selected.length > 0 && selected.length < accounts.length;
            }}
            onChange={(e) => {
              selectionTrigger.current = e.currentTarget;
              select(e.target.checked ? accounts.map((a) => a.tag) : []);
            }}
          />
          Select all {accounts.length} accounts
        </label>
      )}
      {accounts.map((account) => (
        <div
          className={`signup-compact-row ${account.has_staff_placement ? "is-assigned" : ""} ${selected.includes(account.tag) ? "is-selected" : ""}`}
          key={account.tag}
        >
          {editable && (
            <label className="signup-select">
              <input
                type="checkbox"
                aria-label={`Select ${account.player_name || account.tag}`}
                disabled={disabled || busy}
                checked={selected.includes(account.tag)}
                onChange={(e) => {
                  selectionTrigger.current = e.currentTarget;
                  select(
                    e.target.checked
                      ? [...selected, account.tag]
                      : selected.filter((tag) => tag !== account.tag),
                  );
                }}
              />
            </label>
          )}
          <div className="signup-player">
            <div className="signup-player-name">
              <TownHallIcon level={account.town_hall} />
              <strong>{account.player_name || account.tag}</strong>
            </div>
            <small>
              {account.tag} · TH {account.town_hall ?? "—"}
            </small>
          </div>
          <span className="signup-pool">
            {account.pool === "main" ? "Main" : "Lazy"} CWL
          </span>
          <div className="signup-placement">
            {account.has_staff_placement ? (
              <>
                <small>Assigned</small>
                <strong>
                  {account.assigned_clan_name ||
                    account.assigned_clan_tag ||
                    "Clan unavailable"}
                </strong>
              </>
            ) : (
              <span>Awaiting placement</span>
            )}
          </div>
          {editable && (
            <button
              className="signup-manage"
              disabled={disabled || busy}
              aria-expanded={selected.includes(account.tag)}
              onClick={(event) => {
                selectionTrigger.current = event.currentTarget;
                select(
                  selected.length === 1 && selected[0] === account.tag
                    ? []
                    : [account.tag],
                );
              }}
            >
              Edit signup
            </button>
          )}
          {account.fwa_main_warning && (
            <p className="signup-row-warning">
              FWA account signed up for Main CWL. Review with the member.
            </p>
          )}
        </div>
      ))}
      {!!selected.length && (
        <div className="signup-inline-editor">
          <strong>
            Manage {selected.length}{" "}
            {selected.length === 1 ? "account" : "accounts"}
          </strong>
          <p>{chosen.map((a) => a.player_name || a.tag).join(", ")}</p>
          <label>
            Action
            <select
              disabled={busy}
              value={action}
              onChange={(e) => {
                setAction(e.target.value);
                setError("");
              }}
            >
              <option value="">Choose an action</option>
              <option value="main">Change to Main CWL</option>
              <option value="lazy">Change to Lazy CWL</option>
              <option value="remove">Remove signups</option>
            </select>
          </label>
          {action && (
            <p>
              {action === "remove"
                ? `Remove ${affected.length} ${affected.length === 1 ? "signup" : "signups"} from this season.`
                : `Change ${affected.length} ${affected.length === 1 ? "account" : "accounts"} to ${action === "main" ? "Main" : "Lazy"} CWL.`}
              {placed > 0 &&
                ` This clears ${placed} existing clan ${placed === 1 ? "placement" : "placements"}.`}
              {placed > 0 &&
                " Published rosters stay unchanged until republished."}
              {action === "main" &&
                " Accounts currently in FWA clans cannot switch to Main CWL."}
            </p>
          )}
          {error && (
            <p role="alert" className="notice error">
              {error}
            </p>
          )}
          <div className="signup-editor-actions">
            <button
              className={action === "remove" ? "danger" : "primary"}
              disabled={busy || !action || !affected.length}
              onClick={() => void save()}
            >
              {busy
                ? "Saving…"
                : action === "remove"
                  ? "Confirm removal"
                  : "Save changes"}
            </button>
            <button disabled={busy} onClick={cancel}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
