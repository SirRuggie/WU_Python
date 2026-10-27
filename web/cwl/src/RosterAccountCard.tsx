import { useId, useRef } from "react";
import {
  ArrowRightLeft,
  Info,
  LockKeyhole,
  MoreHorizontal,
  UserRoundPen,
} from "lucide-react";
import DiscordContact from "./DiscordContact";
import TownHallIcon from "./TownHallIcon";
import { Button, Chip } from "./rosterUi/primitives";
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
  const menu = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const descriptionId = useId();
  const maySelect = !archived && (canRoster || canSignups);
  const currentClanKnown = account.current_clan_status === "current";
  const closeAnd = (action: () => void) => {
    menu.current?.removeAttribute("open");
    action();
  };
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
            {account.player_name}
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
                  if (trigger.current) onAssign(trigger.current);
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
                  if (trigger.current) onSignup(trigger.current);
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
    </article>
  );
}
