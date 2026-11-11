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
/** The shared DM item for every account ⋯ menu. */
export function discordMessageItem(userId?: string | null): ActionMenuItem {
  const contact = discordContact(userId, true);
  return contact.href
    ? {
        id: "dm",
        label: contact.label,
        href: contact.href,
        title: contact.title,
      }
    : { id: "dm", label: contact.unavailable, disabled: true };
}
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
  items.push(discordMessageItem(account.user_id));
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
