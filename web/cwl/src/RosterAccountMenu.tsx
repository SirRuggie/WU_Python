import { useRef } from "react";
import {
  ArrowRightLeft,
  Info,
  MoreHorizontal,
  UserRoundPen,
} from "lucide-react";
import DiscordContact from "./DiscordContact";
import { Button } from "./rosterUi/primitives";
import type { RosterAccount } from "./roster";
import "./RosterAccountCard.css";

type Props = {
  account: RosterAccount;
  disabled: boolean;
  canRoster?: boolean;
  canSignups?: boolean;
  archived?: boolean;
  onDetails: () => void;
  onAssign?: (trigger: HTMLElement) => void;
  onSignup?: (trigger: HTMLElement) => void;
};
export default function RosterAccountMenu({
  account,
  disabled,
  canRoster = false,
  canSignups = false,
  archived = false,
  onDetails,
  onAssign,
  onSignup,
}: Props) {
  const menu = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const closeAnd = (action: () => void) => {
    menu.current?.removeAttribute("open");
    action();
  };
  return (
    <details
      className="roster-player-menu"
      ref={menu}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          menu.current?.removeAttribute("open");
          trigger.current?.focus();
          event.stopPropagation();
        }
      }}
    >
      <summary
        ref={trigger}
        aria-label={`Actions for ${account.player_name}`}
        aria-disabled={disabled}
        onClick={(event) => {
          if (disabled) event.preventDefault();
        }}
      >
        <MoreHorizontal size={22} aria-hidden="true" />
      </summary>
      <div className="roster-player-actions">
        {canRoster && !archived && (
          <Button
            icon={ArrowRightLeft}
            onClick={() =>
              closeAnd(() => {
                if (trigger.current) onAssign?.(trigger.current);
              })
            }
          >
            Assign
          </Button>
        )}
        {canSignups && !archived && (
          <Button
            icon={UserRoundPen}
            onClick={() =>
              closeAnd(() => {
                if (trigger.current) onSignup?.(trigger.current);
              })
            }
          >
            Change signup
          </Button>
        )}
        <DiscordContact userId={account.user_id} compact />
        <Button icon={Info} onClick={() => closeAnd(onDetails)}>
          Details
        </Button>
      </div>
    </details>
  );
}
