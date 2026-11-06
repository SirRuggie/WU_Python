import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  maxInviteNameLength,
  type InviteRow,
  type InvitesResponse,
} from "./moderationSettingsModel";

type Props = {
  names: Record<string, string>;
  disabled: boolean;
  onName: (code: string, name: string) => void;
};

function expiry(value: string | null) {
  if (!value) return "Never expires";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Expiry unavailable"
    : `Expires ${date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
}

export default function ModerationInviteNames({
  names,
  disabled,
  onName,
}: Props) {
  const [invites, setInvites] = useState<InviteRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const request = useRef(0);

  const load = useCallback(async () => {
    const id = ++request.current;
    setLoading(true);
    setError("");
    try {
      const result = await api<InvitesResponse>(
        "/manage/member-events/invites",
      );
      if (request.current !== id) return;
      setInvites(Array.isArray(result?.invites) ? result.invites : []);
    } catch (cause) {
      if (request.current !== id) return;
      setError(
        cause instanceof Error ? cause.message : "Could not load invites.",
      );
    } finally {
      if (request.current === id) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      request.current += 1;
    };
  }, [load]);

  return (
    <div className="moderation-invite-names">
      <div className="moderation-invite-head">
        <h4>Invite names</h4>
        <button type="button" disabled={loading} onClick={() => void load()}>
          Refresh invites
        </button>
      </div>
      {loading && <small role="status">Loading invites…</small>}
      {error && (
        <small role="alert">{error} Settings can still be saved.</small>
      )}
      {!loading && !error && invites?.length === 0 && (
        <small>No invites recorded yet.</small>
      )}
      {invites && invites.length > 0 && (
        <ul className="moderation-invite-list">
          {invites.map((invite) => {
            const label = invite.vanity ? "Vanity URL" : invite.code;
            return (
              <li key={invite.code}>
                <label>
                  <span className="moderation-invite-code">{label}</span>
                  <input
                    value={names[invite.code] ?? ""}
                    maxLength={maxInviteNameLength}
                    placeholder="Name"
                    disabled={disabled}
                    aria-label={`Name for ${label}`}
                    onChange={(event) =>
                      onName(invite.code, event.target.value)
                    }
                  />
                </label>
                <small>
                  {invite.max_uses
                    ? `${invite.uses} / ${invite.max_uses} uses`
                    : `${invite.uses} uses`}
                  {" · "}
                  {invite.inviter_name || "Unknown inviter"}
                  {invite.channel_name ? ` · #${invite.channel_name}` : ""}
                  {" · "}
                  {expiry(invite.expires_at)}
                </small>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
