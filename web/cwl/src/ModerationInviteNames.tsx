import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
} from "react";
import { api } from "./api";
import LoadError from "./LoadError";
import { Button } from "./rosterUi/primitives";
import {
  inviteNameError,
  type InviteRow,
  type InvitesResponse,
} from "./moderationSettingsModel";

type Props = {
  names: Record<string, string>;
  savedNames?: Record<string, string>;
  resetKey?: string;
  disabled: boolean;
  onName: (code: string, name: string) => void;
};
type Editing = Record<
  string,
  { group: "saved" | "other"; originalName: string }
>;
function expiry(value: string | null) {
  if (!value) return "Never expires";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Expiry unavailable"
    : `Expires ${date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
}
export function rankInviteCodes(
  codes: string[],
  invites: InviteRow[] | null,
  names: Record<string, string>,
) {
  const rows = new Map((invites || []).map((invite) => [invite.code, invite]));
  return [...codes].sort((a, b) => {
    const first = rows.get(a),
      second = rows.get(b);
    if (!!first !== !!second) return first ? -1 : 1;
    return (
      (second?.uses || 0) - (first?.uses || 0) ||
      (names[a] || a).trim().localeCompare((names[b] || b).trim()) ||
      a.localeCompare(b)
    );
  });
}
export default function ModerationInviteNames({
  names,
  savedNames = {},
  resetKey = "",
  disabled,
  onName,
}: Props) {
  const [invites, setInvites] = useState<InviteRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const request = useRef(0);
  const [editing, setEditing] = useState<Editing>({});
  const [othersOpen, setOthersOpen] = useState(false);
  const [focus, setFocus] = useState<{ code: string; input: boolean } | null>(
    null,
  );
  const host = useRef<HTMLDivElement>(null);
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
  useEffect(() => {
    setEditing({});
    setFocus(null);
  }, [resetKey]);
  useLayoutEffect(() => {
    if (!focus) return;
    const attribute = focus.input ? "data-invite-name" : "data-invite-action";
    const target = [
      ...(host.current?.querySelectorAll<HTMLElement>(`[${attribute}]`) || []),
    ].find((node) => node.getAttribute(attribute) === focus.code);
    if (target) {
      target.focus();
      setFocus(null);
    }
  }, [focus, names, editing, othersOpen]);

  const active = new Map(
    (invites || []).map((invite) => [invite.code, invite]),
  );
  const isSaved = (code: string) =>
    editing[code]?.group === "saved" ||
    (!!names[code]?.trim() && editing[code]?.group !== "other");
  const codes = [
    ...new Set([
      ...Object.keys(names),
      ...Object.keys(editing),
      ...active.keys(),
    ]),
  ];
  const saved = rankInviteCodes(codes.filter(isSaved), invites, names);
  const other = [...(invites || [])]
    .filter((invite) => !isSaved(invite.code))
    .sort((a, b) => b.uses - a.uses || a.code.localeCompare(b.code));
  const edit = (code: string, group: "saved" | "other") => {
    setEditing((current) => ({
      ...current,
      [code]: { group, originalName: names[code] || "" },
    }));
    setFocus({ code, input: true });
  };
  const closeEditor = (code: string) =>
    setEditing((current) => {
      const next = { ...current };
      delete next[code];
      return next;
    });
  const commit = (code: string, value: string, explicit = false) => {
    if (inviteNameError(value)) return;
    if (!value.trim() && editing[code]?.group === "other") return;
    if (names[code] !== value) onName(code, value);
    const moved = editing[code]?.group !== (value.trim() ? "saved" : "other");
    closeEditor(code);
    if (!value.trim()) setOthersOpen(true);
    if (moved || explicit) setFocus({ code, input: false });
  };
  const blur = (code: string, event: FocusEvent<HTMLInputElement>) => {
    if (
      event.relatedTarget instanceof Node &&
      event.currentTarget
        .closest(".moderation-invite-editor")
        ?.contains(event.relatedTarget)
    )
      return;
    commit(code, event.currentTarget.value);
  };
  const remove = (code: string) => {
    onName(code, "");
    closeEditor(code);
    setOthersOpen(true);
    setFocus({ code, input: false });
  };
  const metadata = (invite: InviteRow) => (
    <small>
      {invite.inviter_name || "Unknown inviter"}
      {invite.channel_name ? ` · #${invite.channel_name}` : ""}
      {" · "}
      {expiry(invite.expires_at)}
    </small>
  );
  const editor = (
    code: string,
    invite: InviteRow | undefined,
    group: "saved" | "other",
  ) =>
    editing[code] && (
      <div className="moderation-invite-editor">
        <label>
          Name
          <input
            data-invite-name={code}
            value={names[code] ?? ""}
            placeholder="Name"
            disabled={disabled}
            aria-label={`Name for ${invite?.vanity ? "Vanity URL" : code}`}
            aria-invalid={!!inviteNameError(names[code] ?? "")}
            onChange={(event) => onName(code, event.target.value)}
            onBlur={(event) => blur(code, event)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commit(code, event.currentTarget.value, true);
              }
            }}
          />
        </label>
        {inviteNameError(names[code] ?? "") && (
          <small role="alert">{inviteNameError(names[code] ?? "")}</small>
        )}
        {group === "saved" && invite && metadata(invite)}
        {group === "saved" && (
          <Button
            disabled={disabled}
            aria-label={`Remove name for ${code}`}
            onClick={() => remove(code)}
          >
            Remove name
          </Button>
        )}
      </div>
    );
  const unsaved = (code: string) =>
    (names[code] || "").trim() !== (savedNames[code] || "").trim();
  const link = (code: string) => (
    <a
      href={`https://discord.gg/${encodeURIComponent(code)}`}
      target="_blank"
      rel="noreferrer"
    >
      discord.gg/{code}
    </a>
  );

  return (
    <div className="moderation-invite-names" ref={host}>
      <div className="moderation-invite-head">
        <h3>Invite tracking</h3>
        <Button disabled={loading} onClick={() => void load()}>
          Refresh invites
        </Button>
      </div>
      {loading && <small role="status">Loading invites…</small>}
      <LoadError
        message={error}
        note="Settings can still be saved."
        disabled={loading}
        onRetry={() => void load()}
      />
      {!loading && !error && invites?.length === 0 && (
        <small>No invites recorded yet.</small>
      )}
      <h4>Saved links</h4>
      {saved.length === 0 ? (
        <p>No saved links yet.</p>
      ) : (
        <ul className="moderation-invite-list moderation-saved-invites">
          {saved.map((code) => {
            const invite = active.get(code);
            const stale = invites !== null && !invite;
            const name = (
              names[code] ||
              editing[code]?.originalName ||
              ""
            ).trim();
            return (
              <li key={code} data-invite-code={code}>
                <div className="moderation-invite-row-head">
                  <strong>
                    {name}
                    {invite &&
                      ` · ${invite.uses}${invite.max_uses ? ` / ${invite.max_uses}` : ""}`}
                  </strong>
                  <Button
                    data-invite-action={code}
                    disabled={disabled}
                    aria-expanded={!!editing[code]}
                    onClick={() => edit(code, "saved")}
                  >
                    Change
                  </Button>
                </div>
                {link(code)}
                {stale && <small>No longer active</small>}
                {stale && !editing[code] && (
                  <Button
                    disabled={disabled}
                    aria-label={`Remove name for ${code}`}
                    onClick={() => remove(code)}
                  >
                    Remove
                  </Button>
                )}
                {unsaved(code) && (
                  <small className="moderation-invite-unsaved">
                    Unsaved changes
                  </small>
                )}
                {editor(code, invite, "saved")}
              </li>
            );
          })}
        </ul>
      )}
      {invites !== null && (
        <details
          className="moderation-other-invites"
          open={othersOpen}
          onToggle={(event) => setOthersOpen(event.currentTarget.open)}
        >
          <summary>{other.length} other invites</summary>
          <ul className="moderation-invite-list">
            {other.map((invite) => (
              <li key={invite.code} data-invite-code={invite.code}>
                <div className="moderation-invite-row-head">
                  <strong>
                    {link(invite.code)} · {invite.uses}
                    {invite.max_uses ? ` / ${invite.max_uses}` : ""} uses
                  </strong>
                  <Button
                    data-invite-action={invite.code}
                    disabled={disabled}
                    aria-expanded={!!editing[invite.code]}
                    onClick={() => edit(invite.code, "other")}
                  >
                    Name
                  </Button>
                </div>
                {metadata(invite)}
                {unsaved(invite.code) && (
                  <small className="moderation-invite-unsaved">
                    Unsaved changes
                  </small>
                )}
                {editor(invite.code, invite, "other")}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
