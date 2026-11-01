import {
  useId,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import type { Account, Clan, Session } from "./api";
import DashboardIcon from "./DashboardIcon";
import DiscordIdentity from "./DiscordIdentity";
import { clanDeepLink } from "./publication";
import TownHallIcon from "./TownHallIcon";
import { weightText } from "./roster";
import "./PlayerClanDetailsDialog.css";

type Freshness = "current" | "partial" | "saved" | "unavailable";

type CommonProps = {
  freshness: Freshness;
  loadedAt?: string | null;
  onClose: () => void;
  children?: ReactNode;
  returnFocusFallbackId?: string;
};

export type PlayerClanDetailsProps = CommonProps &
  (
    | { kind: "player"; account: Account; session?: Session }
    | {
        kind: "clan";
        tag: string;
        name: string;
        badgeUrl?: string | null;
        clan?: Clan;
        linkedAccounts?: Account[];
      }
  );

export function safeClanBadgeUrl(value?: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      url.hostname === "api-assets.clashofclans.com" &&
      url.pathname.startsWith("/badges/") &&
      !url.port &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash
      ? value
      : null;
  } catch {
    return null;
  }
}

export function detailsFreshnessText(
  kind: "player" | "clan",
  freshness: Freshness,
  loadedAt?: string | null,
) {
  const subject = kind === "player" ? "Player details" : "Clan details";
  const date =
    loadedAt && Number.isFinite(Date.parse(loadedAt))
      ? new Date(loadedAt).toLocaleString([], {
          dateStyle: "medium",
          timeStyle: "short",
        })
      : null;
  if (freshness === "partial")
    return `${subject} are still loading and may be incomplete.`;
  if (freshness === "saved")
    return `Showing saved ${kind} data${date ? ` from ${date}` : ""}; refresh to confirm changes.`;
  if (freshness === "unavailable")
    return kind === "clan"
      ? "Some clan details could not be refreshed."
      : "Current player details are unavailable.";
  return date
    ? `${subject} loaded ${date}.`
    : `${subject} from the latest available read.`;
}

export default function PlayerClanDetailsDialog(props: PlayerClanDetailsProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const statusId = useId();

  useLayoutEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const dialog = dialogRef.current;
    dialog?.showModal();
    dialog
      ?.querySelector<HTMLButtonElement>(".player-clan-details-close")
      ?.focus({ preventScroll: true });
    return () => {
      dialog?.close();
      requestAnimationFrame(() => {
        if (
          opener?.isConnected &&
          opener.getClientRects().length &&
          !opener.closest("[inert]")
        ) {
          opener.focus({ preventScroll: true });
        } else if (props.returnFocusFallbackId) {
          document
            .getElementById(props.returnFocusFallbackId)
            ?.focus({ preventScroll: true });
        }
      });
    };
  }, []);

  function containFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") return;
    const controls = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
      ) || [],
    ).filter(
      (control) =>
        control.getClientRects().length > 0 &&
        !control.closest("[inert], [hidden]"),
    );
    const first = controls[0],
      last = controls[controls.length - 1];
    if (!first || !last) return;
    if (
      event.shiftKey &&
      (document.activeElement === first ||
        document.activeElement === dialogRef.current)
    ) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const player = props.kind === "player" ? props.account : null;
  const clanMembers =
    props.kind === "clan"
      ? (props.linkedAccounts || []).filter(
          (account) => account.current_clan_tag === props.tag,
        )
      : [];
  const name = player?.name || (props.kind === "clan" ? props.name : "");
  const tag = player?.tag || (props.kind === "clan" ? props.tag : "");
  const badgeUrl =
    props.kind === "clan" ? safeClanBadgeUrl(props.badgeUrl) : null;

  return createPortal(
    <dialog
      ref={dialogRef}
      className="player-clan-details"
      aria-labelledby={titleId}
      aria-describedby={statusId}
      onCancel={(event) => {
        event.preventDefault();
        props.onClose();
      }}
      onKeyDown={containFocus}
    >
      <header className="player-clan-details-head">
        <div className="player-clan-details-icon" aria-hidden="true">
          {player ? (
            <TownHallIcon level={player.town_hall} />
          ) : badgeUrl ? (
            <img src={badgeUrl} alt="" referrerPolicy="no-referrer" />
          ) : (
            <DashboardIcon name="shield" />
          )}
        </div>
        <div className="player-clan-details-identity">
          <p className="eyebrow">{player ? "Linked player" : "Clan"}</p>
          <h2 id={titleId}>{name}</h2>
          <span>{tag}</span>
        </div>
        <button
          className="player-clan-details-close"
          type="button"
          onClick={props.onClose}
          aria-label={`Close ${player ? "player" : "clan"} details`}
        >
          Close ×
        </button>
      </header>
      <p className="player-clan-details-freshness" id={statusId}>
        {detailsFreshnessText(props.kind, props.freshness, props.loadedAt)}
      </p>
      {player ? (
        <>
          <dl className="player-clan-details-facts">
            <div>
              <dt>Town Hall</dt>
              <dd>
                {player.town_hall == null ? "Unavailable" : player.town_hall}
              </dd>
            </div>
            <div title="Roster weight; not a measure of player skill">
              <dt>Roster weight</dt>
              <dd>
                {player.war_weight == null
                  ? "Unavailable"
                  : weightText(player.war_weight)}
              </dd>
            </div>
          </dl>
          <section className="player-clan-details-section">
            <h3>Current clan</h3>
            <p>
              {player.current_clan_name ||
                player.current_clan_tag ||
                "No current clan available"}
              {player.current_clan_name && player.current_clan_tag ? (
                <small> {player.current_clan_tag}</small>
              ) : null}
            </p>
            {player.current_clan_tag && (
              <small>
                {player.family_clan_status === "approved"
                  ? "Warriors United family clan"
                  : player.family_clan_status === "outside"
                    ? "Outside the family directory"
                    : "Family status unknown"}
              </small>
            )}
          </section>
          {props.kind === "player" && props.session && (
            <section className="player-clan-details-section">
              <h3>Your Discord account</h3>
              <DiscordIdentity
                userId={props.session.user.id}
                resolvedMember={props.session.user}
                contact={false}
              />
            </section>
          )}
        </>
      ) : (
        props.kind === "clan" && (
          <>
            <p className="player-clan-details-clan-meta">
              {props.clan
                ? props.clan.archived
                  ? "Archived family entry"
                  : "Family clan"
                : "Clan of a linked player"}
              {props.clan?.cwl_league && (
                <>
                  {" "}
                  · CWL league: {props.clan.cwl_league}
                  {props.clan.cwl_league_stale ? " (may be outdated)" : ""}
                </>
              )}
            </p>
            <section className="player-clan-details-section">
              <h3>Your linked players here</h3>
              <p>
                {props.freshness === "unavailable"
                  ? "Linked player count is unavailable while account data cannot load."
                  : props.freshness === "partial"
                    ? `${clanMembers.length} linked player${clanMembers.length === 1 ? "" : "s"} available so far in this clan. The list may be incomplete.`
                    : `${clanMembers.length} of your linked player${clanMembers.length === 1 ? "" : "s"} currently shown in this clan. This is not the full clan roster.`}
              </p>
              {clanMembers.length > 0 && (
                <details>
                  <summary>Show linked players</summary>
                  <ul>
                    {clanMembers.map((account) => (
                      <li key={account.tag}>
                        <strong>{account.name}</strong>
                        <span>
                          {account.tag}
                          {account.town_hall == null
                            ? ""
                            : ` · TH ${account.town_hall}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </section>
          </>
        )
      )}
      {props.children}
      <footer className="player-clan-details-footer">
        <a
          href={
            player
              ? `https://link.clashofclans.com/en?action=OpenPlayerProfile&tag=${encodeURIComponent(tag)}`
              : clanDeepLink(tag)
          }
          target="_blank"
          rel="noopener noreferrer"
        >
          Open {player ? "player" : "clan"} in Clash of Clans ↗
        </a>
      </footer>
    </dialog>,
    document.body,
  );
}
