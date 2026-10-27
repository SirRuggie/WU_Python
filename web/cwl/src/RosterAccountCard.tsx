import { useId } from "react";
import { LockKeyhole } from "lucide-react";
import RosterAccountMenu from "./RosterAccountMenu";
import TownHallIcon from "./TownHallIcon";
import { Chip } from "./rosterUi/primitives";
import { compactRosterWeight } from "./rosterCompactWeight";
import type { RosterAccount } from "./roster";
import "./RosterAccountCard.css";

type Props = {
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
  const currentClanKnown = account.current_clan_status === "current";
  return (
    <article
      className={`roster-player-card${account.assigned_clan_tag ? " is-assigned" : ""}${selected ? " is-selected" : ""}`}
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
        className="roster-player-body"
        aria-describedby={descriptionId}
        disabled={disabled}
        aria-label={
          selectionMode && maySelect
            ? `${selected ? "Deselect" : "Select"} ${account.player_name}`
            : `Details for ${account.player_name}`
        }
        onClick={selectionMode && maySelect ? onToggle : onDetails}
      >
        <span className="roster-player-identity">
          <strong>
            <TownHallIcon level={account.town_hall} />
            <span className="roster-player-name">{account.player_name}</span>
          </strong>
          <small>
            {account.tag} · TH {account.town_hall ?? "—"}
            {showPool
              ? ` · ${account.pool === "main" ? "Main" : "Lazy"} CWL`
              : ""}
          </small>
        </span>
        <span className="roster-player-weight">
          {account.effective_weight == null ? (
            <Chip tone="danger">No weight</Chip>
          ) : (
            <strong>{compactRosterWeight(account.effective_weight)}</strong>
          )}
        </span>
        <span className="roster-player-assignment">
          <small>Assigned clan</small>
          <strong>
            {account.kept && (
              <LockKeyhole size={15} aria-label="Locked placement" />
            )}
            {assignedClanName}
          </strong>
        </span>
        <span className="roster-player-current">
          <small>
            Current clan
            {account.current_clan_status === "stale" ? " · Last checked" : ""}
          </small>
          <span className={currentClanKnown ? undefined : "is-unknown"}>
            {currentClanKnown
              ? account.current_clan_name ||
                account.current_clan_tag ||
                "No clan"
              : "—"}
          </span>
        </span>
        {account.outside_family_and_hosts && (
          <span className="roster-player-warning">
            <Chip tone="warning">Outside family / hosting clans</Chip>
          </span>
        )}
        {!account.assigned_clan_tag &&
          (account.kept || account.auto_placement_reason !== "ready") && (
            <small className="roster-player-note">
              {account.kept
                ? "Held unassigned · unlock in Details to auto-place"
                : account.auto_placement_note || "Not assigned"}
            </small>
          )}
      </button>
      <span id={descriptionId} className="roster-player-sr-only">
        {account.tag}. TH {account.town_hall ?? "unknown"}. Weight{" "}
        {compactRosterWeight(account.effective_weight)}. Assigned clan:{" "}
        {assignedClanName}.{account.kept ? " Locked placement." : ""}
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
