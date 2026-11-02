import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import ConfirmDialog from "../ConfirmDialog";
import RoleSelect from "../RoleSelect";
import DiscordIdentity, { type DiscordProfile } from "../DiscordIdentity";
import { MemberPages } from "../memberTimezones/NicknameReview";
type RefusedTarget = {
  discord_id: string;
  reason: string;
  discord_profile: DiscordProfile | null;
};
import type { RoleChoice } from "../CommandExtras";
import type { RoleReview } from "./useRoleRun";
import { membersText as t } from "./strings";
export default function RoleChangeReview({
  ids,
  operation,
  roles,
  onCancel,
  onConfirm,
  onDenied,
  fixedRole,
  guardRoleIds,
  onError = () => {},
  returnFocus,
}: {
  ids: readonly string[];
  operation: "add" | "remove";
  roles: RoleChoice[];
  onCancel: () => void;
  onConfirm: (review: RoleReview) => Promise<boolean>;
  onDenied: () => void;
  fixedRole?: string;
  guardRoleIds?: readonly string[];
  onError?: (message: string) => void;
  returnFocus?: () => HTMLElement | null;
}) {
  const [role, setRole] = useState(fixedRole || ""),
    [review, setReview] = useState<RoleReview | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [attempt, setAttempt] = useState(0),
    [blocked, setBlocked] = useState<RefusedTarget[]>([]),
    [blockedPage, setBlockedPage] = useState(0);
  const pending = useRef(false),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const single = !!fixedRole && ids.length === 1;
  useEffect(() => {
    if (single) void prepare();
  }, []);
  // The caller freezes IDs when opening this surface; filters cannot change them.
  async function prepare() {
    if (!role || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setBlocked([]);
    setBlockedPage(0);
    try {
      const next = await api<RoleReview>(
        "/manage/members/role-preview",
        "POST",
        {
          member_ids: ids,
          role_id: role,
          operation,
          ...(guardRoleIds ? { guard_role_ids: guardRoleIds } : {}),
        },
      );
      if (!alive.current) return;
      if (
        !next ||
        typeof next.token !== "string" ||
        !next.token ||
        !next.role ||
        typeof next.role.name !== "string" ||
        typeof next.role.protected !== "boolean" ||
        !Array.isArray(next.selected) ||
        next.count !== ids.length ||
        next.selected.length !== ids.length ||
        new Set(next.selected).size !== ids.length ||
        next.selected.some((id) => !ids.includes(id)) ||
        next.role.id !== role ||
        next.operation !== operation
      )
        throw new Error(t.roleReviewChanged);
      if (single && !next.role.protected) {
        await onConfirm(next);
        if (alive.current) onCancel();
      } else setReview(next);
    } catch (cause) {
      if (!alive.current) return;
      if (cause instanceof ApiError && [401, 403].includes(cause.status))
        onDenied();
      const body =
        cause instanceof ApiError
          ? (cause.responseData as { code?: string; blocked?: RefusedTarget[] })
          : undefined;
      const refused =
        body?.code === "member_targets_refused" &&
        Array.isArray(body.blocked) &&
        body.blocked.every(
          (row) =>
            row &&
            ids.includes(row.discord_id) &&
            typeof row.reason === "string",
        )
          ? body.blocked
          : [];
      setBlocked(refused);
      setError(cause instanceof Error ? cause.message : t.roleUnavailable);
      setAttempt((value) => value + 1);
      if (single) {
        onError(
          refused[0]?.reason ||
            (cause instanceof Error ? cause.message : t.roleUnavailable),
        );
        onCancel();
      }
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function confirm() {
    if (!review || pending.current) return;
    pending.current = true;
    setBusy(true);
    let accepted = false;
    try {
      accepted = await onConfirm(review);
    } catch {
      if (alive.current) {
        setError(t.roleUncertain);
        onError(t.roleUncertain);
      }
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
    if (!alive.current) return;
    if (accepted || single) onCancel();
    else {
      setReview(null);
      setAttempt((value) => value + 1);
    }
  }
  if (single && !review) return null;
  const text = review
    ? operation === "add"
      ? t.addConfirm(review.role.name, review.count)
      : t.removeConfirm(review.role.name, review.count)
    : t.chooseRole(ids.length);
  return (
    <ConfirmDialog
      returnFocus={returnFocus}
      key={`${review ? "confirm" : "choose"}-${attempt}`}
      heading={operation === "add" ? t.addRole : t.removeRole}
      text={text}
      confirmLabel={
        review
          ? operation === "add"
            ? t.addRole
            : t.removeRole
          : t.reviewChanges
      }
      cancelLabel={t.keepRole}
      disabled={busy || (!review && !role)}
      onCancel={() => {
        if (!pending.current) onCancel();
      }}
      onConfirm={() => void (review ? confirm() : prepare())}
    >
      {!review && (
        <RoleSelect
          label={t.roles}
          roles={roles}
          value={role}
          onChange={(value) => {
            setRole(value);
            setBlocked([]);
            setError("");
          }}
          disabled={busy}
        />
      )}
      {review?.role.protected && <p role="status">{t.protectedRole}</p>}
      {error && <p role="alert">{error}</p>}
      {!!blocked.length && (
        <section aria-label={t.refusedPeople}>
          <p>{t.refusedCount(blocked.length)}</p>
          <ul>
            {blocked
              .slice(blockedPage * 25, blockedPage * 25 + 25)
              .map((row) => (
                <li key={row.discord_id}>
                  <DiscordIdentity
                    userId={row.discord_id}
                    resolvedMember={row.discord_profile || null}
                    contact={false}
                    variant="compact"
                  />
                  <span>{row.reason}</span>
                </li>
              ))}
          </ul>
          <MemberPages
            page={blockedPage}
            total={blocked.length}
            onChange={setBlockedPage}
          />
        </section>
      )}
    </ConfirmDialog>
  );
}
