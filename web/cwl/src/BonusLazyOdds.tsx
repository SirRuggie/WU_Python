import type { RefObject } from "react";
import SearchPicker from "./SearchPicker";
import { roleOption } from "./RolePicker";

type Role = { id: string; name: string };

type Props = {
  detailsRef: RefObject<HTMLDetailsElement | null>;
  roles: Role[];
  roleId: string;
  rolesLoading: boolean;
  rolesError: string;
  disabled: boolean;
  canSave: boolean;
  onOpen: () => void;
  onRetryRoles: () => void;
  onRole: (id: string) => void;
  onSave: () => void;
};

/** FWA Rep odds settings (Lazy only). */
export default function BonusLazyOdds({
  detailsRef,
  roles,
  roleId,
  rolesLoading,
  rolesError,
  disabled,
  canSave,
  onOpen,
  onRetryRoles,
  onRole,
  onSave,
}: Props) {
  return (
    <details
      ref={detailsRef}
      className="bonus-secondary"
      onToggle={(event) => {
        if (event.currentTarget.open) onOpen();
      }}
    >
      <summary>FWA Rep odds settings</summary>
      <p>
        Members with this Discord role get 2 chances in Lazy draws. Each account
        can win only one time. With 2 chances, an account does not always have
        twice the chance to win when the draw picks more than one winner.
      </p>
      {rolesLoading && <p role="status">Loading roles…</p>}
      {rolesError && (
        <p role="alert">
          {rolesError}{" "}
          <button type="button" onClick={onRetryRoles}>
            Retry roles
          </button>
        </p>
      )}
      <SearchPicker
        label="Representative role"
        value={roleId}
        options={roles.map(roleOption)}
        fallback={{ value: roleId, label: "Saved role (not found)" }}
        disabled={disabled}
        placeholder="Select a role…"
        searchPlaceholder="Role name…"
        emptyText="No roles match."
        onChange={onRole}
      />
      <button type="button" disabled={!canSave} onClick={onSave}>
        Save role
      </button>
    </details>
  );
}
