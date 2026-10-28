import { useId } from "react";
import PlayerCardMeta from "./PlayerCardMeta";
import RosterAccountMenu from "./RosterAccountMenu";
import TownHallIcon from "./TownHallIcon";
import { Chip } from "./rosterUi/primitives";
import { compactRosterWeight } from "./rosterCompactWeight";
import PlayerClanStatus, { playerClanStatus } from "./PlayerClanStatus";
import type { RosterAccount } from "./roster";
import "./PlayerCard.css";
import "./RosterAccountCard.css";

type Props = {
  now: number;
  account: RosterAccount;
  assignedClanName: string;
  showPool: boolean;
  selected: boolean;
  selectionMode: boolean;
  disabled: boolean;
  canRoster: boolean;
  canSignups: boolean;
  archived: boolean;
  onToggle: () => void;
  onDetails: () => void;
  onAssign: (trigger: HTMLElement) => void;
  onSignup: (trigger: HTMLElement) => void;
};

export default function RosterAccountCard({
  now,
  account,
  assignedClanName,
  showPool,
  selected,
  selectionMode,
  disabled,
  canRoster,
  canSignups,
  archived,
  onToggle,
  onDetails,
  onAssign,
  onSignup,
}: Props) {
  const descriptionId = useId();
  const maySelect = !archived && (canRoster || canSignups);
  const status = playerClanStatus(
    account.assigned_clan_tag,
    assignedClanName,
    account,
    now,
  );
  return (
    <article
      className={`player-card player-card-responsive roster-player-card${account.assigned_clan_tag ? " is-assigned" : ""}${selected ? " is-selected" : ""}`}
    >
      <label className="roster-player-select">
        <input
          type="checkbox"
          checked={selected}
          disabled={disabled || !maySelect}
          onChange={onToggle}
          aria-label={`Select ${account.player_name} for bulk actions`}
        />
      </label>
      <button
        type="button"
        className="player-card-body roster-player-body"
        aria-describedby={descriptionId}
        disabled={disabled}
        aria-label={
          selectionMode && maySelect
            ? `${selected ? "Deselect" : "Select"} ${account.player_name}`
            : `Details for ${account.player_name}`
        }
        onClick={selectionMode && maySelect ? onToggle : onDetails}
      >
        <span className="player-card-top">
          <span aria-hidden="true">
            <TownHallIcon level={account.town_hall} />
          </span>
          <strong className="player-card-name" title={account.player_name}>
            {account.player_name}
          </strong>
          <span className="player-card-weight">
            {account.effective_weight == null ? (
              <Chip tone="danger">No weight</Chip>
            ) : (
              <strong>{compactRosterWeight(account.effective_weight)}</strong>
            )}
          </span>
        </span>
        <PlayerCardMeta account={account} showPool={showPool} />
        <PlayerClanStatus status={status} />
        {account.outside_family_and_hosts && (
          <span className="roster-player-warning">
            <Chip tone="warning">Outside family / hosting clans</Chip>
          </span>
        )}
        {!account.assigned_clan_tag &&
          (account.kept ||
            (account.auto_placement_reason !== "ready" &&
              !!account.auto_placement_note)) && (
            <small className="roster-player-note">
              {account.kept
                ? "Held unassigned · unlock in Details to auto-place"
                : account.auto_placement_note}
            </small>
          )}
      </button>
      <span id={descriptionId} className="roster-player-sr-only">
        {account.tag}. Town Hall {account.town_hall ?? "unknown"}.
        {showPool ? ` ${account.pool === "main" ? "Main" : "Lazy"} CWL.` : ""}{" "}
        Weight {compactRosterWeight(account.effective_weight)}.{" "}
        {status.description}
        {account.kept ? " Locked placement." : ""}
      </span>
      <RosterAccountMenu
        account={account}
        disabled={disabled}
        canRoster={canRoster}
        canSignups={canSignups}
        archived={archived}
        onDetails={onDetails}
        onAssign={onAssign}
        onSignup={onSignup}
      />
    </article>
  );
}
