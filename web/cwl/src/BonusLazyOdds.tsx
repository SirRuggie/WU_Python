import SearchPicker from "./SearchPicker";
import { roleOption } from "./RolePicker";

type Role = { id: string; name: string };

type Props = {
  roles: Role[];
  roleId: string;
  rolesLoading: boolean;
  rolesError: string;
  disabled: boolean;
  canSave: boolean;
  onRetryRoles: () => void;
  onRole: (id: string) => void;
  onSave: () => void;
};

/** FWA Rep role for Lazy draw odds; one section of the Settings sheet. */
export default function BonusLazyOdds({
  roles,
  roleId,
  rolesLoading,
  rolesError,
  disabled,
  canSave,
  onRetryRoles,
  onRole,
  onSave,
}: Props) {
  return (
    <section className="results-settings-section" aria-label="Lazy draw odds">
      <h3>Lazy draw odds</h3>
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
    </section>
  );
}
