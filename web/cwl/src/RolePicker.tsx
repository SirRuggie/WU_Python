import { useState } from "react";
import "./RolePicker.css";

export type RoleChoice = {
  id: string;
  name: string;
  managed?: boolean;
  position?: number;
  color?: number;
};
export default function RolePicker({
  roles,
  selected,
  disabled,
  onChoose,
  label,
  optionsLabel,
}: {
  roles: RoleChoice[];
  selected: string[];
  disabled: boolean;
  onChoose: (role: RoleChoice) => void;
  label: string;
  optionsLabel: string;
}) {
  const [query, setQuery] = useState("");
  // Discord supplies server order; filtering must not re-sort it by name.
  const available = roles.filter(
    (role) =>
      !role.managed &&
      !selected.includes(role.id) &&
      role.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  return (
    <div className="role-picker">
      <label>
        {label}
        <input
          type="search"
          value={query}
          disabled={disabled}
          placeholder="Search role names"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <div className="strikes-role-options" aria-label={optionsLabel}>
        {available.map((role) => (
          <button
            type="button"
            key={role.id}
            title={role.id}
            disabled={disabled}
            onClick={() => onChoose(role)}
          >
            <span
              className="role-picker-color"
              aria-hidden="true"
              style={{
                backgroundColor:
                  Number.isInteger(role.color) &&
                  role.color! > 0 &&
                  role.color! <= 0xffffff
                    ? `#${role.color!.toString(16).padStart(6, "0")}`
                    : "#aeb9c7",
              }}
            />
            {role.name}
            <span aria-hidden="true">＋</span>
          </button>
        ))}
        {!available.length && <p>No matching roles available.</p>}
      </div>
    </div>
  );
}
