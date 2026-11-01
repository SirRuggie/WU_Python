import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import ConfirmDialog from "../ConfirmDialog";
import RoleSelect from "../RoleSelect";
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
}: {
  ids: readonly string[];
  operation: "add" | "remove";
  roles: RoleChoice[];
  onCancel: () => void;
  onConfirm: (review: RoleReview) => Promise<boolean>;
  onDenied: () => void;
}) {
  const [role, setRole] = useState(""),
    [review, setReview] = useState<RoleReview | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [attempt, setAttempt] = useState(0);
  const pending = useRef(false),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // The caller freezes IDs when opening this surface; filters cannot change them.
  async function prepare() {
    if (!role || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await api<RoleReview>(
        "/manage/members/role-preview",
        "POST",
        { member_ids: ids, role_id: role, operation },
      );
      if (!alive.current) return;
      if (
        !next ||
        !Array.isArray(next.selected) ||
        next.count !== ids.length ||
        next.selected.length !== ids.length ||
        new Set(next.selected).size !== ids.length ||
        next.selected.some((id) => !ids.includes(id)) ||
        next.role.id !== role ||
        next.operation !== operation
      )
        throw new Error(t.roleReviewChanged);
      setReview(next);
    } catch (cause) {
      if (!alive.current) return;
      if (cause instanceof ApiError && [401, 403].includes(cause.status))
        onDenied();
      setError(cause instanceof Error ? cause.message : t.roleUnavailable);
      setAttempt((value) => value + 1);
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function confirm() {
    if (!review || pending.current) return;
    pending.current = true;
    setBusy(true);
    const accepted = await onConfirm(review);
    pending.current = false;
    if (!alive.current) return;
    if (accepted) onCancel();
    else {
      setBusy(false);
      setReview(null);
      setAttempt((value) => value + 1);
    }
  }
  const text = review
    ? operation === "add"
      ? t.addConfirm(review.role.name, review.count)
      : t.removeConfirm(review.role.name, review.count)
    : t.chooseRole(ids.length);
  return (
    <ConfirmDialog
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
          onChange={setRole}
          disabled={busy}
        />
      )}
      {review?.role.protected && <p role="status">{t.protectedRole}</p>}
      {error && <p role="alert">{error}</p>}
    </ConfirmDialog>
  );
}
