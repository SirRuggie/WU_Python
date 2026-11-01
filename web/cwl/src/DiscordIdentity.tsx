import { useEffect, useState } from "react";
import { api } from "./api";
import type { MemberOption } from "./MemberPicker";
import DiscordContact from "./DiscordContact";
import "./DiscordIdentity.css";

export type DiscordProfile = Pick<MemberOption, "id"> &
  Partial<Pick<MemberOption, "display_name" | "username" | "avatar_url">>;
/** Also use this for native form/ARIA labels that cannot contain a profile card. */
export function discordIdentityName(
  userId?: string | null,
  profile?: DiscordProfile | null,
  displayName?: string | null,
) {
  return [profile?.display_name, profile?.username, displayName]
    .find((n) => typeof n === "string" && n.trim() && n.trim() !== userId)
    ?.trim();
}
/** One identity renderer. Rows supply a page-level batch result; dialogs may resolve once. */
export default function DiscordIdentity({
  userId,
  resolvedMember,
  displayName,
  linkStatus,
  resolving = false,
  variant = "full",
  contact = true,
  username = true,
  diagnostics = false,
  className = "",
}: {
  userId?: string | null;
  resolvedMember?: DiscordProfile | null;
  displayName?: string | null;
  linkStatus?: string | null;
  resolving?: boolean;
  variant?: "full" | "compact";
  contact?: boolean;
  username?: boolean;
  diagnostics?: boolean;
  className?: string;
}) {
  const [member, setMember] = useState<DiscordProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [failedAvatar, setFailedAvatar] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const validId = !!userId && /^\d{15,22}$/.test(userId);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setMember(null);
    setFailed(false);
    setFailedAvatar(null);
    setLoading(validId);
    if (!validId || resolvedMember !== undefined) {
      setLoading(false);
      return;
    }
    void api<{ options: MemberOption[] }>(
      `/staff-signup-members?id=${encodeURIComponent(userId!)}`,
      "GET",
      undefined,
      { signal: controller.signal },
    )
      .then((result) => {
        if (active)
          setMember(
            result.options.find((option) => option.id === userId) || null,
          );
      })
      .catch(() => {
        if (active && !controller.signal.aborted) setFailed(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [userId, validId, retry, resolvedMember]);
  const supplied = resolvedMember === undefined ? member : resolvedMember;
  const profile = supplied?.id === userId ? supplied : null;
  const profileLoading = resolvedMember === undefined ? loading : resolving;
  const name = discordIdentityName(userId, profile, displayName);
  const Root = variant === "compact" ? "span" : "section";
  if (
    linkStatus &&
    ["conflict", "unknown", "pending", "unlinked"].includes(linkStatus)
  )
    return (
      <Root
        className={`roster-discord-identity discord-identity-${variant} ${className}`}
      >
        <small>
          {linkStatus === "conflict"
            ? "Discord link needs review"
            : linkStatus === "unlinked"
              ? "No Discord account linked"
              : "Discord member unavailable"}
        </small>
      </Root>
    );
  if (!validId && !name)
    return (
      <Root
        className={`roster-discord-identity discord-identity-${variant} ${className}`}
      >
        <small>No Discord account linked</small>
      </Root>
    );
  const url = profile?.avatar_url;
  const avatar =
    typeof url === "string" &&
    failedAvatar !== url &&
    (url.startsWith("https://cdn.discordapp.com/") ||
      /^\/api\/cwl\/manage\/member-events\/[a-zA-Z0-9_-]+\/avatar$/.test(url))
      ? url
      : null;
  return (
    <Root
      role="group"
      className={`roster-discord-identity discord-identity-${variant} ${className}`}
      aria-label="Linked Discord member"
      aria-busy={profileLoading}
    >
      {avatar ? (
        <img
          className="user-avatar"
          src={avatar}
          alt=""
          width={36}
          height={36}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailedAvatar(avatar)}
        />
      ) : (
        <span
          className="roster-discord-avatar user-avatar user-avatar-fallback"
          aria-hidden="true"
        >
          {name ? Array.from(name)[0].toUpperCase() : "?"}
        </span>
      )}
      <span className="roster-discord-person">
        <strong className="user-display-name">
          {name ||
            (profileLoading
              ? "Loading Discord member…"
              : "Discord member unavailable")}
        </strong>
        {username && profile?.username && profile.username !== userId && (
          <small>@{profile.username}</small>
        )}
        {failed && (
          <small role="status">
            Could not load profile.{" "}
            <button type="button" onClick={() => setRetry((n) => n + 1)}>
              Retry
            </button>
          </small>
        )}
        {diagnostics && validId && (
          <details>
            <summary>Discord details</summary>
            <small>
              Discord ID: <code>{userId}</code>
            </small>
          </details>
        )}
      </span>
      {contact && <DiscordContact userId={userId} compact />}
    </Root>
  );
}
