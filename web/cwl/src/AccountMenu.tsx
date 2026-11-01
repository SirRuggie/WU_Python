import { ChevronDown, LogOut, RotateCcw } from "lucide-react";
import {
  Button as AriaButton,
  Menu,
  MenuItem,
  MenuTrigger,
  Popover,
  Separator,
} from "react-aria-components";
import type { Session } from "./api";
import { discordIdentityName } from "./DiscordIdentity";
import { AccountIdentity } from "./AccountIdentity";
import "./AccountMenu.css";

type Props = {
  user: Session["user"];
  onSignOut: () => void;
  variant: "profile" | "avatar";
  disabled?: boolean;
  replayPrank?: () => void;
};

export default function AccountMenu({
  user,
  onSignOut,
  variant,
  disabled = false,
  replayPrank,
}: Props) {
  const name =
    discordIdentityName(user.id, user) || "Discord member unavailable";

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
            <AccountIdentity user={user} />
          </div>
          <Separator className="account-menu-separator" />
          <Menu
            aria-label={`Account actions for ${name}`}
            className="account-menu-list"
          >
            {replayPrank && (
              <MenuItem
                className="account-menu-signout"
                textValue="Replay prank"
                isDisabled={disabled}
                onAction={replayPrank}
              >
                <RotateCcw size={17} aria-hidden="true" />
                <span>Replay prank</span>
              </MenuItem>
            )}
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
