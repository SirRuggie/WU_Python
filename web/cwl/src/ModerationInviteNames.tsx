import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  inviteNameError,
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

  const stale = invites
    ? Object.keys(names).filter(
        (code) => !invites.some((invite) => invite.code === code),
      )
    : [];

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
                    placeholder="Name"
                    disabled={disabled}
                    aria-label={`Name for ${label}`}
                    aria-invalid={!!inviteNameError(names[invite.code] ?? "")}
                    onChange={(event) =>
                      onName(invite.code, event.target.value)
                    }
                  />
                </label>
                {inviteNameError(names[invite.code] ?? "") && (
                  <small role="alert">
                    {inviteNameError(names[invite.code] ?? "")}
                  </small>
                )}
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
      {stale.length > 0 && (
        <ul className="moderation-invite-list">
          {stale.map((code) => (
            <li key={code}>
              <label>
                <span className="moderation-invite-code">{code}</span>
                <input
                  value={names[code]}
                  placeholder="Name"
                  disabled={disabled}
                  aria-label={`Name for ${code}`}
                  aria-invalid={!!inviteNameError(names[code])}
                  onChange={(event) => onName(code, event.target.value)}
                />
              </label>
              {inviteNameError(names[code]) && (
                <small role="alert">{inviteNameError(names[code])}</small>
              )}
              <small>No longer active</small>
              <button
                type="button"
                disabled={disabled}
                aria-label={`Remove name for ${code}`}
                onClick={() => onName(code, "")}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
