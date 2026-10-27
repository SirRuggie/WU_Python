import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Plus, Search, UserRoundSearch } from "lucide-react";
import { api, type Account, type Pool } from "./api";
import MemberPicker from "./MemberPicker";
import TownHallIcon from "./TownHallIcon";
import useUnsavedWork from "./useUnsavedWork";
import RosterMenu from "./rosterUi/Menu";
import { Button, Input, StatusPill } from "./rosterUi/primitives";
import "./StaffTagSignup.css";

type Lookup = {
  account: Account;
  linked_user_id: string | null;
  signed_up_pool: Pool | null;
};
type Props = {
  seasonId: string;
  onSaved: () => Promise<void>;
  onDirty: (dirty: boolean) => void;
  onBusy: (busy: boolean) => void;
};

const poolOptions = [
  { value: "", label: "Choose Main or Lazy" },
  { value: "main", label: "Main CWL" },
  { value: "lazy", label: "Lazy CWL" },
];

export default function StaffTagSignup({
  seasonId,
  onSaved,
  onDirty,
  onBusy,
}: Props) {
  const [tag, setTag] = useState("");
  const [result, setResult] = useState<Lookup | null>(null);
  const [hasDiscord, setHasDiscord] = useState(false);
  const [uid, setUid] = useState("");
  const [searchMember, setSearchMember] = useState(false);
  const [pool, setPool] = useState<Pool | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const sequence = useRef(0);

  useUnsavedWork(!saved && !!tag.trim(), onDirty);
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);

  async function lookup() {
    const turn = ++sequence.current;
    setBusy(true);
    setError("");
    setResult(null);
    setSaved(false);
    try {
      const data = await api<Lookup>(
        `/seasons/${seasonId}/staff-signups/player?tag=${encodeURIComponent(tag.trim())}`,
      );
      if (turn !== sequence.current) return;
      setResult(data);
      setUid(data.linked_user_id || "");
      setHasDiscord(!!data.linked_user_id);
      setSearchMember(false);
      setPool("");
    } catch (cause) {
      if (turn === sequence.current) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not find this player.",
        );
      }
    } finally {
      if (turn === sequence.current) setBusy(false);
    }
  }

  async function add() {
    if (!result || !pool || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/seasons/${seasonId}/staff-signups/player`, "POST", {
        tag: result.account.tag,
        pool,
        prefer_crystal_1_or_lower: false,
        has_discord: hasDiscord,
        user_id: hasDiscord ? uid.trim() : "",
        expected_linked_user_id: result.linked_user_id,
      });
      setSaved(true);
      try {
        await onSaved();
      } catch {
        setError("Signup saved. Refresh the page to update the roster.");
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not add signup.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="staff-tag-signup">
      <p>Enter a player tag. We’ll check for a linked Discord account.</p>
      <div className="staff-tag-lookup">
        <Input
          label="Player tag"
          value={tag}
          disabled={busy}
          placeholder="#ABC123"
          maxLength={20}
          onChange={(event) => {
            setTag(event.target.value);
            setResult(null);
            setSaved(false);
            setError("");
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && tag.trim()) {
              event.preventDefault();
              void lookup();
            }
          }}
        />
        <Button
          icon={Search}
          disabled={busy || !tag.trim()}
          onClick={() => void lookup()}
        >
          {busy && !result ? "Checking…" : "Find player"}
        </Button>
      </div>
      {result && (
        <div className="staff-tag-result">
          <div className="staff-tag-player">
            <TownHallIcon level={result.account.town_hall} />
            <div>
              <strong>{result.account.name}</strong>
              <small>
                {result.account.tag} ·{" "}
                {result.account.current_clan_name || "No clan"}
              </small>
            </div>
          </div>
          {saved ? (
            <p className="notice success" role="status">
              <StatusPill tone="success">
                <CheckCircle2 size={14} aria-hidden="true" /> Saved
              </StatusPill>
              Signup added. Use Roster builder to assign a clan.
            </p>
          ) : result.signed_up_pool ? (
            <p className="notice" role="status">
              Already signed up for{" "}
              {result.signed_up_pool === "main" ? "Main" : "Lazy"} CWL. Open
              Manage account in Saved signups to change its clan placement.
            </p>
          ) : (
            <fieldset disabled={busy}>
              {result.linked_user_id ? (
                <p>
                  <StatusPill tone="success">Linked Discord account</StatusPill>{" "}
                  <strong>{result.linked_user_id}</strong>
                </p>
              ) : (
                <>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={hasDiscord}
                      onChange={(event) => {
                        setHasDiscord(event.target.checked);
                        setUid("");
                        setSearchMember(false);
                      }}
                    />
                    Has a Discord account
                  </label>
                  {!hasDiscord && (
                    <p className="small">
                      No Discord link found. You can add this player without
                      Discord.
                    </p>
                  )}
                </>
              )}
              {hasDiscord && !result.linked_user_id && (
                <>
                  <Input
                    label="Discord ID"
                    inputMode="numeric"
                    placeholder="Enter Discord user ID"
                    value={uid}
                    onChange={(event) => setUid(event.target.value)}
                    maxLength={22}
                  />
                  <Button
                    icon={UserRoundSearch}
                    onClick={() => setSearchMember((value) => !value)}
                    aria-expanded={searchMember}
                  >
                    {searchMember
                      ? "Hide member search"
                      : "Find a server member"}
                  </Button>
                  {searchMember && (
                    <MemberPicker
                      label="Discord account for signup"
                      value={uid}
                      onChange={(value) => setUid(String(value || ""))}
                      disabled={busy}
                      endpoint="/staff-signup-members"
                      showRoles={false}
                    />
                  )}
                  <p className="small">
                    This connects the member to this signup only.
                  </p>
                </>
              )}
              <RosterMenu
                label="CWL type"
                value={pool}
                onValueChange={(value) => setPool(value as Pool | "")}
                options={poolOptions}
                disabled={busy}
              />
              <Button
                variant="primary"
                icon={Plus}
                disabled={
                  busy ||
                  !pool ||
                  (hasDiscord && !/^\d{15,22}$/.test(uid.trim()))
                }
                onClick={() => void add()}
              >
                {busy ? "Saving…" : "Add signup"}
              </Button>
            </fieldset>
          )}
        </div>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
