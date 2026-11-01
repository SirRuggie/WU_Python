import { useState } from "react";
import type { RoleChoice } from "./CommandExtras";

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
  const [search, setSearch] = useState("");
  return (
    <div>
      <label>
        Find a role
        <input
          type="search"
          onFocus={onOpen}
          disabled={disabled}
          value={search}
          placeholder="Type part of a role name"
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      <label>
        {label}
        <select
          value={value}
          onFocus={onOpen}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Choose a role</option>
          {value && !roles.some((role) => role.id === value) && (
            <option value={value}>{unavailableLabel}</option>
          )}
          {roles
            .filter(
              (role) =>
                role.id === value ||
                role.name.toLowerCase().includes(search.toLowerCase()),
            )
            .map((role) => (
              <option key={role.id} value={role.id}>
                {role.name}
              </option>
            ))}
        </select>
      </label>
    </div>
  );
}
