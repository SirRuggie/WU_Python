import { useId } from "react";
import { LockKeyhole } from "lucide-react";
import RosterAccountMenu from "./RosterAccountMenu";
import TownHallIcon from "./TownHallIcon";
import { Chip } from "./rosterUi/primitives";
import { compactRosterWeight } from "./rosterCompactWeight";
import { comparisonAge } from "./comparisonLocation";
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
  const currentClanKnown = Number.isFinite(
    Date.parse(account.current_clan_checked_at || ""),
  );
  const assigned = !!account.assigned_clan_tag;
  const inAssignedClan =
    assigned &&
    currentClanKnown &&
    account.current_clan_tag === account.assigned_clan_tag;
  const currentClanName =
    account.current_clan_name || account.current_clan_tag || "in no clan";
  const age = comparisonAge(account.current_clan_checked_at, now);
  const currentClanText = !currentClanKnown
    ? "· location not checked yet"
    : inAssignedClan
      ? `· in clan · ${age}`
      : `→ ${currentClanName} · ${age}`;
  const minutes = Math.max(
    0,
    Math.floor(
      (now - Date.parse(account.current_clan_checked_at || "")) / 60000,
    ),
  );
  const locationDescription = currentClanKnown
    ? ` Now in ${account.current_clan_name || account.current_clan_tag || "no clan"}, checked ${minutes === 0 ? "just now" : `${minutes} minute${minutes === 1 ? "" : "s"} ago`}.`
    : " Location not checked yet.";
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
        <span className="player-card-meta">
          TH {account.town_hall ?? "—"} · {account.tag}
          {showPool
            ? ` · ${account.pool === "main" ? "Main" : "Lazy"} CWL`
            : ""}
          {account.kept && (
            <LockKeyhole size={13} aria-label="Locked placement" />
          )}
        </span>
        <span
          title={`${assigned ? assignedClanName : "Not assigned"} ${currentClanText}`}
          className={`roster-player-placement${inAssignedClan ? " is-in-clan" : assigned && currentClanKnown ? " is-elsewhere" : ""}${!assigned ? " is-unassigned" : ""}`}
        >
          <strong>
            {account.assigned_clan_tag ? assignedClanName : "Not assigned"}
          </strong>
          <span className="roster-player-current" title={currentClanText}>
            {currentClanText}
          </span>
        </span>
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
        {account.tag}. TH {account.town_hall ?? "unknown"}. Weight{" "}
        {compactRosterWeight(account.effective_weight)}. Assigned clan:{" "}
        {account.assigned_clan_tag ? assignedClanName : "Not assigned"}.
        {locationDescription}
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
