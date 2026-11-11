import type { RoleChoice } from "./CommandExtras";
import { roleOption } from "./RolePicker";
import SearchPicker from "./SearchPicker";

export default function RoleSelect({
  roles,
  value,
  onChange,
  disabled = false,
  label = "Role",
  onOpen,
  unavailableLabel = "Unavailable role",
}: {
  roles: RoleChoice[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  label?: string;
  onOpen?: () => void;
  unavailableLabel?: string;
}) {
  return (
    <SearchPicker
      label={label}
      value={value}
      options={roles.map(roleOption)}
      onChange={onChange}
      placeholder="Select a role"
      searchPlaceholder="Type part of a role name"
      emptyText="No matching roles."
      disabled={disabled}
      clearable
      onOpen={onOpen}
      fallback={{ value, label: unavailableLabel }}
    />
  );
}
