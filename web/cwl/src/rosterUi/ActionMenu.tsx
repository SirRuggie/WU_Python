import { useInteractOutside } from "react-aria";
import { useEffect, useId, useRef, useSyncExternalStore } from "react";
import {
  Button as AriaButton,
  Menu,
  MenuTrigger,
  Popover,
} from "react-aria-components";
import { MoreHorizontal, type LucideIcon } from "lucide-react";
import {
  activeRosterActionMenu,
  setRosterActionMenu,
  subscribeRosterActionMenus,
} from "./actionMenuState";
import { RosterMenuItem } from "./Menu";
import "./ActionMenu.css";
export type ActionMenuItem = {
  id: string;
  label: string;
  icon?: LucideIcon;
  onAction?: (trigger: HTMLElement) => void;
  href?: string;
  disabled?: boolean;
};
export default function ActionMenu({
  name,
  items,
  disabled = false,
}: {
  name: string;
  items: ActionMenuItem[];
  disabled?: boolean;
}) {
  const id = useId(),
    trigger = useRef<HTMLButtonElement>(null),
    menu = useRef<HTMLDivElement>(null);
  const active = useSyncExternalStore(
    subscribeRosterActionMenus,
    activeRosterActionMenu,
    () => null,
  );
  const open = active === id && !disabled;
  const close = () => {
    if (activeRosterActionMenu() === id) setRosterActionMenu(null);
  };
  // Non-modal menus permit switching directly to another card trigger.
  // React Aria owns outside interactions even when the target cannot take focus.
  useInteractOutside({
    ref: menu,
    isDisabled: !open,
    onInteractOutside: (event) => {
      if (!trigger.current?.contains(event.target as Node)) close();
    },
  });
  useEffect(
    () => () => {
      if (activeRosterActionMenu() === id) setRosterActionMenu(null);
    },
    [id],
  );
  useEffect(() => {
    if (disabled) close();
  }, [disabled]);
  useEffect(() => {
    if (!open) return;
    const scroll = (event: Event) => {
      if (
        window.matchMedia("(max-width: 720px)").matches &&
        !menu.current?.contains(event.target as Node)
      )
        close();
    };
    window.addEventListener("scroll", scroll, true);
    return () => window.removeEventListener("scroll", scroll, true);
  }, [open]);
  return (
    <div className="roster-player-menu">
      <MenuTrigger
        isOpen={open}
        onOpenChange={(value) => (value ? setRosterActionMenu(id) : close())}
      >
        <AriaButton
          ref={trigger}
          className="roster-action-trigger"
          aria-label={`Actions for ${name}`}
          isDisabled={disabled}
        >
          <MoreHorizontal size={22} aria-hidden="true" />
        </AriaButton>
        <Popover
          className="roster-action-popover roster-ui"
          placement="bottom end"
          isNonModal
        >
          <Menu
            ref={menu}
            aria-label={`Actions for ${name}`}
            className="roster-action-list"
          >
            {items.map((item) => (
              <RosterMenuItem
                key={item.id}
                id={item.id}
                textValue={item.label}
                className="roster-action-item"
                isDisabled={item.disabled}
                href={item.href}
                target={item.href ? "_blank" : undefined}
                rel={item.href ? "noopener noreferrer" : undefined}
                onAction={() => {
                  close();
                  if (trigger.current) item.onAction?.(trigger.current);
                }}
              >
                {item.icon && <item.icon size={18} aria-hidden="true" />}
                <span>{item.label}</span>
              </RosterMenuItem>
            ))}
          </Menu>
        </Popover>
      </MenuTrigger>
    </div>
  );
}
