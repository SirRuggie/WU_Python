import { useInteractOutside } from "react-aria";
import {
  useContext,
  useEffect,
  useId,
  useRef,
  useSyncExternalStore,
} from "react";
import { ActionPanelPortalContext } from "../actionPanelPortal";
import {
  Button as AriaButton,
  Menu,
  MenuTrigger,
  Popover,
  Separator,
} from "react-aria-components";
import { MoreHorizontal, type LucideIcon } from "lucide-react";
import {
  activeRosterActionMenu,
  setRosterActionMenu,
  subscribeRosterActionMenus,
} from "./actionMenuState";
import { RosterMenuItem } from "./Menu";
import useOpeningPressGuard from "./useOpeningPressGuard";
import "./ActionMenu.css";
export type ActionMenuItem = {
  id: string;
  label: string;
  icon?: LucideIcon;
  onAction?: (trigger: HTMLElement) => void;
  href?: string;
  disabled?: boolean;
  title?: string;
  separatorBefore?: boolean;
  danger?: boolean;
};
export default function ActionMenu({
  name,
  label,
  items,
  disabled = false,
}: {
  name: string;
  label?: string;
  items: ActionMenuItem[];
  disabled?: boolean;
}) {
  const portalContainer = useContext(ActionPanelPortalContext);
  const id = useId(),
    trigger = useRef<HTMLButtonElement>(null),
    sheet = useRef<HTMLDivElement>(null);
  const guard = useOpeningPressGuard(trigger, disabled, () => close());
  const active = useSyncExternalStore(
    subscribeRosterActionMenus,
    activeRosterActionMenu,
    () => null,
  );
  const open = active === id && !disabled;
  const close = () => {
    guard.release();
    if (activeRosterActionMenu() === id) setRosterActionMenu(null);
  };
  // Non-modal menus permit switching directly to another card trigger.
  // React Aria owns outside interactions even when the target cannot take focus.
  useInteractOutside({
    ref: sheet,
    isDisabled: !open,
    onInteractOutside: (event) => {
      if (!trigger.current?.contains(event.target as Node)) close();
    },
  });
  useEffect(
    () => () => {
      guard.release();
      if (activeRosterActionMenu() === id) setRosterActionMenu(null);
    },
    [id],
  );
  useEffect(() => {
    if (disabled) close();
  }, [disabled]);
  useEffect(() => {
    if (!open) guard.release();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const scroll = (event: Event) => {
      if (
        window.matchMedia("(max-width: 720px)").matches &&
        !sheet.current?.contains(event.target as Node)
      )
        close();
    };
    window.addEventListener("scroll", scroll, true);
    return () => window.removeEventListener("scroll", scroll, true);
  }, [open]);
  return (
    <div className="roster-player-menu" {...guard.rootProps}>
      <MenuTrigger
        isOpen={open}
        onOpenChange={(value) => (value ? setRosterActionMenu(id) : close())}
      >
        <AriaButton
          ref={trigger}
          className="roster-action-trigger"
          aria-label={label || `Actions for ${name}`}
          isDisabled={disabled}
        >
          <MoreHorizontal size={22} aria-hidden="true" />
          {label && <span>{label}</span>}
        </AriaButton>
        <Popover
          UNSTABLE_portalContainer={portalContainer}
          {...guard.popoverProps}
          ref={sheet}
          className="roster-action-popover roster-ui"
          placement="bottom end"
          isNonModal
        >
          <h3 className="roster-action-heading">{name}</h3>
          <Menu
            aria-label={label || `Actions for ${name}`}
            className="roster-action-list"
          >
            {items.flatMap((item) => [
              ...(item.separatorBefore
                ? [
                    <Separator
                      key={`${item.id}-separator`}
                      className="roster-action-separator"
                    />,
                  ]
                : []),
              <RosterMenuItem
                key={item.id}
                id={item.id}
                textValue={item.label}
                className={`roster-action-item${item.danger ? " roster-action-danger" : ""}`}
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
                <span title={item.title}>{item.label}</span>
              </RosterMenuItem>,
            ])}
          </Menu>
        </Popover>
      </MenuTrigger>
    </div>
  );
}
