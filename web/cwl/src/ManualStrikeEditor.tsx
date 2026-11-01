import DiscordIdentity, { type DiscordProfile } from "./DiscordIdentity";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import ConfirmDialog from "./ConfirmDialog";

type Account = {
  tag: string;
  name: string;
  town_hall?: number | null;
  current_clan_name?: string | null;
  current_clan_tag?: string | null;
};
type Member = {
  id: string;
  name: string;
  accounts: Account[];
  discord_profile?: DiscordProfile;
};
type Props = {
  initialAccount?: {
    player_tag: string;
    player_name: string;
    current_clan_name?: string | null;
  } | null;
  onCancel: () => void;
  onSaved: () => Promise<void>;
  onDirty: (dirty: boolean) => void;
  onBusy: (busy: boolean) => void;
};
const message = (cause: unknown) =>
  cause instanceof Error
    ? cause.message
    : "Could not load accounts. Try again.";

export default function ManualStrikeEditor({
  initialAccount,
  onCancel,
  onSaved,
  onDirty,
  onBusy,
}: Props) {
  const [choosing, setChoosing] = useState(!initialAccount);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Member[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [member, setMember] = useState<Member | null>(null);
  const [account, setAccount] = useState<Account | null>(
    initialAccount
      ? {
          tag: initialAccount.player_tag,
          name: initialAccount.player_name,
          current_clan_name: initialAccount.current_clan_name,
        }
      : null,
  );
  const tag = account?.tag || "";
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState(false);
  const [retry, setRetry] = useState(0);
  const [discarding, setDiscarding] = useState(false);
  const initialTag = useRef(initialAccount?.player_tag || "");
  const sequence = useRef(0);
  const submitting = useRef(false);
  const requestId = useRef(crypto.randomUUID());
  const heading = useRef<HTMLHeadingElement>(null);
  const dirty = !!(reason || query || tag !== initialTag.current || review);
  const name =
    account?.name && account.name !== tag
      ? account.name
      : "Player name unavailable";
  useEffect(() => {
    heading.current?.focus();
  }, [review]);
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    const turn = ++sequence.current;
    if (!choosing || member || query.trim().length < 2) {
      setLoading(false);
      return;
    }
    setMatches([]);
    setAccounts([]);
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      void api<{ members: Member[]; accounts: Account[] }>(
        `/strikes/targets?query=${encodeURIComponent(query.trim())}`,
      )
        .then((data) => {
          if (turn === sequence.current) {
            setMatches(data.members);
            setAccounts(data.accounts);
          }
        })
        .catch((cause) => {
          if (turn === sequence.current) setError(message(cause));
        })
        .finally(() => {
          if (turn === sequence.current) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      sequence.current++;
    };
  }, [query, choosing, member, retry]);
  async function choose(value: Member) {
    const turn = ++sequence.current;
    setAccount(null);
    setMember(null);
    setMatches([]);
    setAccounts([]);
    setLoading(true);
    setError("");
    try {
      const data = await api<{ member: Member }>(
        `/strikes/members/${encodeURIComponent(value.id)}/accounts`,
      );
      if (turn !== sequence.current) return;
      setMember(data.member);
      setAccounts(data.member.accounts);
      // Require an explicit account choice, even for a member with one account.
    } catch (cause) {
      if (turn === sequence.current) setError(message(cause));
    } finally {
      if (turn === sequence.current) setLoading(false);
    }
  }
  async function save() {
    if (submitting.current || !review || !tag.trim() || !reason.trim()) return;
    submitting.current = true;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      await api("/strikes/manual", "POST", {
        player_tag: tag.trim(),
        reason: reason.trim(),
        request_id: requestId.current,
      });
      onDirty(false);
      await onSaved();
    } catch (cause) {
      setError(message(cause));
    } finally {
      submitting.current = false;
      setBusy(false);
      onBusy(false);
    }
  }
  return (
    <section
      className="card strikes-form"
      aria-label="Add strike"
      aria-busy={busy}
    >
      {discarding && (
        <ConfirmDialog
          heading="Unsaved changes"
          text="Discard this unsaved strike?"
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          disabled={busy}
          onCancel={() => setDiscarding(false)}
          onConfirm={() => {
            if (submitting.current) return;
            setDiscarding(false);
            onDirty(false);
            onCancel();
          }}
        />
      )}
      <h2 ref={heading} tabIndex={-1}>
        {review ? "Review strike" : "Add a strike"}
      </h2>
      {error && (
        <div className="notice error" role="alert">
          {error}
          {!review && (
            <button
              type="button"
              onClick={() => setRetry((value) => value + 1)}
            >
              Retry lookup
            </button>
          )}
        </div>
      )}
      {review ? (
        <>
          <dl className="strike-review">
            <div>
              <dt>Account</dt>
              <dd>
                {name}
                {name !== tag && <small>{tag}</small>}
              </dd>
            </div>
            {member && (
              <div>
                <dt>Discord member</dt>
                <dd>
                  <DiscordIdentity
                    userId={member.id}
                    displayName={member.name}
                    resolvedMember={member.discord_profile || null}
                  />
                </dd>
              </div>
            )}
            <div>
              <dt>Reason</dt>
              <dd>{reason}</dd>
            </div>
            <div>
              <dt>Current clan</dt>
              <dd>{account?.current_clan_name || "Clan unavailable"}</dd>
            </div>
          </dl>
          <p>This adds one manual strike to this account.</p>
          <div className="strikes-inline">
            <button disabled={busy} onClick={() => setReview(false)}>
              Back
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Confirm strike"}
            </button>
          </div>
        </>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!choosing && tag.trim() && reason.trim() && !loading)
              setReview(true);
          }}
        >
          <fieldset disabled={busy}>
            {!choosing && account ? (
              <div className="strike-target-identity">
                <p>
                  Adding a strike to <strong>{name}</strong> ·{" "}
                  {account.current_clan_name || "Clan unavailable"}
                </p>
                <small>{tag}</small>
                <button
                  type="button"
                  onClick={() => {
                    setChoosing(true);
                    setQuery("");
                    setMember(null);
                    setAccounts([]);
                    setMatches([]);
                  }}
                >
                  Change
                </button>
              </div>
            ) : (
              <>
                <label>
                  Find player or Discord member
                  <input
                    type="search"
                    value={query}
                    maxLength={80}
                    onChange={(event) => {
                      sequence.current++;
                      setQuery(event.target.value);
                      setMember(null);
                      setMatches([]);
                      setAccounts([]);
                    }}
                    placeholder="Name, tag or Discord member"
                  />
                </label>
                {loading && <p role="status">Looking up accounts…</p>}
                {!loading &&
                  !error &&
                  (accounts.length > 0 || matches.length > 0) && (
                    <div className="strike-member-matches">
                      {accounts.map((item) => (
                        <button
                          type="button"
                          key={item.tag}
                          onClick={() => {
                            sequence.current++;
                            setAccount(item);
                            setChoosing(false);
                            setQuery("");
                            setError("");
                          }}
                        >
                          <strong>
                            {item.name === item.tag
                              ? "Player name unavailable"
                              : item.name}
                          </strong>
                          <small>
                            {item.tag} · TH {item.town_hall ?? "unknown"} ·{" "}
                            {item.current_clan_name || "Clan unavailable"}
                          </small>
                        </button>
                      ))}
                      {matches.map((item) => (
                        <button
                          type="button"
                          key={item.id}
                          onClick={() => void choose(item)}
                        >
                          <DiscordIdentity
                            userId={item.id}
                            displayName={item.name}
                            resolvedMember={item.discord_profile || null}
                            variant="compact"
                            contact={false}
                          />
                          <small>Choose account</small>
                        </button>
                      ))}
                    </div>
                  )}
                {member && <p>Accounts linked to {member.name}</p>}
                {!loading &&
                  !error &&
                  query.trim().length >= 2 &&
                  !accounts.length &&
                  !matches.length && (
                    <p>
                      No matching accounts or members. Try a player tag or
                      another name.
                    </p>
                  )}
                {account && (
                  <button
                    type="button"
                    onClick={() => {
                      setChoosing(false);
                      setQuery("");
                      setError("");
                    }}
                  >
                    Keep current account
                  </button>
                )}
              </>
            )}
            <label>
              Reason
              <input
                required
                maxLength={500}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why is this strike needed?"
              />
            </label>
          </fieldset>
          <div className="strikes-inline">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (submitting.current) return;
                if (dirty) setDiscarding(true);
                else onCancel();
              }}
            >
              Cancel
            </button>
            <button
              className="primary"
              disabled={
                busy || choosing || loading || !tag.trim() || !reason.trim()
              }
            >
              Review strike
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
