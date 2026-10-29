import { discordContact } from "./DiscordContact";
import { ArrowRightLeft, Info, UserRoundPen } from "lucide-react";
import ActionMenu, { type ActionMenuItem } from "./rosterUi/ActionMenu";
import type { RosterAccount } from "./roster";

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
export function rosterAccountMenuItems({
  account,
  canRoster = false,
  canSignups = false,
  archived = false,
  onDetails,
  onAssign,
  onSignup,
}: Omit<Props, "disabled">): ActionMenuItem[] {
  const items: ActionMenuItem[] = [];
  if (canRoster && !archived)
    items.push({
      id: "assign",
      label: "Assign",
      icon: ArrowRightLeft,
      onAction: onAssign,
    });
  if (canSignups && !archived)
    items.push({
      id: "signup",
      label: "Change signup",
      icon: UserRoundPen,
      onAction: onSignup,
    });
  const contact = discordContact(account.user_id, true);
  items.push(
    contact.href
      ? {
          id: "dm",
          label: contact.label,
          href: contact.href,
          title: contact.title,
        }
      : { id: "dm", label: contact.unavailable, disabled: true },
  );
  items.push({
    id: "details",
    label: "Details",
    icon: Info,
    onAction: onDetails,
  });
  return items;
}
export default function RosterAccountMenu(props: Props) {
  return (
    <ActionMenu
      name={props.account.player_name}
      disabled={props.disabled}
      items={rosterAccountMenuItems(props)}
    />
  );
}
