import { useState, type ComponentProps, type MouseEvent } from "react";
import { Check, ChevronDown } from "lucide-react";
import { Menu as AriaMenu, MenuItem } from "react-aria-components";
import type { LucideIcon } from "lucide-react";
import ActionPanel from "../ActionPanel";
import "./tokens.css";
import "./primitives.css";

export type RosterMenuOption = {
  value: string;
  label: string;
  disabled?: boolean;
  icon?: LucideIcon;
};

export type RosterMenuProps = {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: RosterMenuOption[];
  disabled?: boolean;
  autoFocus?: boolean;
  id?: string;
  "aria-label"?: string;
};

export function commitRosterMenuAction(
  value: string,
  options: RosterMenuOption[],
  onValueChange: (nextValue: string) => void,
) {
  const option = options.find((item) => item.value === value);
  if (!option || option.disabled) return false;
  onValueChange(option.value);
  return true;
}

// Shared accessible item for selection menus and the action-popover variant.
export function RosterMenuItem(props: ComponentProps<typeof MenuItem>) {
  return <MenuItem {...props} />;
}

export default function RosterMenu({
  label,
  value,
  onValueChange,
  options,
  disabled = false,
  autoFocus = false,
  id,
  "aria-label": ariaLabel,
}: RosterMenuProps) {
  const [open, setOpen] = useState(false);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const selected = options.find((option) => option.value === value);
  const openMenu = (event: MouseEvent<HTMLButtonElement>) => {
    setTrigger(event.currentTarget);
    setOpen(true);
  };
  const activate = (nextValue: string) => {
    if (disabled) return;
    if (!commitRosterMenuAction(nextValue, options, onValueChange)) return;
    setOpen(false);
  };

  return (
    <div className="roster-ui roster-menu">
      <button
        id={id}
        autoFocus={autoFocus}
        ref={setTrigger}
        type="button"
        className="roster-menu-trigger"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={openMenu}
      >
        <span className="roster-menu-trigger-copy">
          <span className="roster-menu-label">{label}</span>
          <span className="roster-menu-current">
            {selected?.label || "Choose an option"}
          </span>
        </span>
        <ChevronDown className="roster-menu-chevron" aria-hidden="true" />
      </button>
      {open && !disabled && (
        <ActionPanel
          title={label}
          trigger={trigger}
          onClose={() => setOpen(false)}
          className="roster-ui"
        >
          <div className="roster-ui roster-menu-panel">
            <AriaMenu
              aria-label={ariaLabel || label}
              className="roster-menu-list"
            >
              {options.map((option) => {
                const Icon = option.icon;
                return (
                  <RosterMenuItem
                    key={option.value}
                    id={option.value}
                    textValue={option.label}
                    aria-label={
                      option.value === value
                        ? `${option.label}, selected`
                        : option.label
                    }
                    isDisabled={option.disabled}
                    className="roster-menu-item"
                    onAction={() => activate(option.value)}
                  >
                    {Icon && (
                      <Icon className="roster-ui-icon" aria-hidden="true" />
                    )}
                    <span className="roster-menu-item-label">
                      {option.label}
                    </span>
                    {option.value === value && (
                      <Check
                        className="roster-menu-item-check"
                        aria-hidden="true"
                      />
                    )}
                  </RosterMenuItem>
                );
              })}
            </AriaMenu>
          </div>
        </ActionPanel>
      )}
    </div>
  );
}
