import { ChevronDown, LogOut } from "lucide-react";
import {
  Button as AriaButton,
  Menu,
  MenuItem,
  MenuTrigger,
  Popover,
  Separator,
} from "react-aria-components";
import type { Session } from "./api";
import { AccountIdentity } from "./AccountIdentity";
import "./AccountMenu.css";

type Props = {
  user: Session["user"];
  onSignOut: () => void;
  variant: "profile" | "avatar";
  disabled?: boolean;
};

export default function AccountMenu({
  user,
  onSignOut,
  variant,
  disabled = false,
}: Props) {
  const name = user.display_name || user.username;

  return (
    <div className={`account-menu account-menu-${variant}`}>
      <MenuTrigger>
        <AriaButton
          className={`account-menu-trigger account-menu-${variant}-trigger`}
          aria-label={variant === "avatar" ? "Account menu" : undefined}
          isDisabled={disabled}
        >
          <AccountIdentity user={user} />
          {variant === "profile" && (
            <>
              <small className="account-menu-handle">@{user.username}</small>
              <ChevronDown
                className="account-menu-chevron"
                size={16}
                aria-hidden="true"
              />
            </>
          )}
        </AriaButton>
        <Popover
          className="account-menu-popover"
          placement={variant === "avatar" ? "bottom end" : "top start"}
        >
          <div className="account-menu-summary">
            <span>Signed in as</span>
            <strong>{name}</strong>
            <small>@{user.username}</small>
          </div>
          <Separator className="account-menu-separator" />
          <Menu
            aria-label={`Account actions for ${name}`}
            className="account-menu-list"
          >
            <MenuItem
              className="account-menu-signout"
              textValue="Sign out"
              isDisabled={disabled}
              onAction={onSignOut}
            >
              <LogOut size={17} aria-hidden="true" />
              <span>Sign out</span>
            </MenuItem>
          </Menu>
        </Popover>
      </MenuTrigger>
    </div>
  );
}
