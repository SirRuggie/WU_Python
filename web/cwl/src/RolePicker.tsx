import SearchPicker, { type PickerOption } from "./SearchPicker";
import "./RolePicker.css";

export type RoleChoice = {
  id: string;
  name: string;
  managed?: boolean;
  position?: number;
  color?: number;
};

/** Picker row for a role: its name with a dot in the role colour. */
export function roleOption(role: RoleChoice): PickerOption {
  return {
    value: role.id,
    label: role.name,
    icon: (
      <span
        className="role-picker-color"
        style={{
          backgroundColor:
            Number.isInteger(role.color) &&
            role.color! > 0 &&
            role.color! <= 0xffffff
              ? `#${role.color!.toString(16).padStart(6, "0")}`
              : "#aeb9c7",
        }}
      />
    ),
  };
}

/** Search field that adds one role at a time; the field itself stays empty. */
export default function RolePicker({
  roles,
  selected,
  disabled,
  onChoose,
  label,
}: {
  roles: RoleChoice[];
  selected: string[];
  disabled: boolean;
  onChoose: (role: RoleChoice) => void;
  label: string;
}) {
  // Discord supplies server order; filtering must not re-sort it by name.
  const available = roles.filter(
    (role) => !role.managed && !selected.includes(role.id),
  );
  return (
    <SearchPicker
      label={label}
      value=""
      options={available.map(roleOption)}
      onChange={(id) => {
        const role = available.find((item) => item.id === id);
        if (role) onChoose(role);
      }}
      placeholder="Add a role"
      searchPlaceholder="Search role names"
      emptyText="No matching roles available."
      disabled={disabled}
    />
  );
}
