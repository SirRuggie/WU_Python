import { useState, type ComponentProps, type MouseEvent } from "react";
import { Check, ChevronDown } from "lucide-react";
import { Menu as AriaMenu, MenuItem } from "react-aria-components";
import type { LucideIcon } from "lucide-react";
import ActionPanel from "../ActionPanel";
import { Input } from "./primitives";
import "./tokens.css";
import "./primitives.css";

export type RosterMenuOption = {
  value: string;
  label: string;
  disabled?: boolean;
  description?: string;
  icon?: LucideIcon;
};

export type RosterMenuProps = {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: RosterMenuOption[];
  disabled?: boolean;
  autoFocus?: boolean;
  searchable?: boolean;
  searchLabel?: string;
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
  searchable = false,
  searchLabel = "Find a clan",
  id,
  "aria-label": ariaLabel,
}: RosterMenuProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const selected = options.find((option) => option.value === value);
  const normalizedSearch = search.trim().normalize("NFKC").toLocaleLowerCase();
  const matching = options.filter(
    (option) =>
      !searchable ||
      `${option.label} ${option.value}`
        .normalize("NFKC")
        .toLocaleLowerCase()
        .includes(normalizedSearch),
  );
  const openMenu = (event: MouseEvent<HTMLButtonElement>) => {
    setSearch("");
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
          expandOnSearchFocus={searchable}
        >
          <div className="roster-ui roster-menu-panel">
            {searchable && (
              <Input
                label={searchLabel}
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Clan name or tag"
                autoFocus
              />
            )}
            {searchable && !matching.length && (
              <p>No clans match this search.</p>
            )}
            <AriaMenu
              aria-label={ariaLabel || label}
              className="roster-menu-list"
            >
              {matching.map((option) => {
                const Icon = option.icon;
                return (
                  <RosterMenuItem
                    key={option.value}
                    id={option.value}
                    textValue={option.label}
                    aria-label={`${option.label}${option.value === value ? ", selected" : ""}${option.description ? `. ${option.description}` : ""}`}
                    isDisabled={option.disabled}
                    className="roster-menu-item"
                    onAction={() => activate(option.value)}
                  >
                    {Icon && (
                      <Icon className="roster-ui-icon" aria-hidden="true" />
                    )}
                    <span className="roster-menu-item-label">
                      {option.label}
                      {option.description && (
                        <small className="roster-menu-item-description">
                          {option.description}
                        </small>
                      )}
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
