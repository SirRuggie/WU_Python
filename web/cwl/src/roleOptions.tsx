import type { PickerOption } from "./SearchPicker";

type RoleLike = { id: string; name: string; color?: number };

function roleColor(color?: number) {
  return Number.isInteger(color) && color! > 0 && color! <= 0xffffff
    ? `#${color!.toString(16).padStart(6, "0")}`
    : "#aeb9c7";
}

/** Picker row for a Discord role, with its colour as a dot. Never shows the ID. */
export function roleOption(role: RoleLike): PickerOption {
  return {
    value: role.id,
    label: role.name,
    icon: (
      <span
        style={{
          display: "inline-block",
          width: 12,
          height: 12,
          borderRadius: "50%",
          backgroundColor: roleColor(role.color),
        }}
      />
    ),
  };
}
