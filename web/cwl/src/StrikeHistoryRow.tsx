import { useState, type ReactNode } from "react";
import {
  CheckCircle2,
  Clock3,
  MinusCircle,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import type { Entry } from "./StrikesWorkspace";
import { strikeLinkLabel } from "./strikeHistoryView";

function statusText(item: Entry) {
  if (item.kind === "mismatch") return "Mismatch war (no strike)";
  if (item.kind === "no_attack") return "No-attack war (no strike)";
  if (item.status === "removed") return "Removed";
  if (item.status === "exempt") return "Exempt (no strike)";
  if (item.kind === "cwl")
    return item.attacks_used === 1
      ? "CWL attack used (no strike)"
      : "CWL miss (no strike)";
  if (item.kind === "miss") return "One attack missed (no strike)";
  if (item.kind === "completed") return "Attacks done (no strike)";
  return item.status === "expired" ? "Expired" : "Active";
}
export default function StrikeHistoryRow({
  item,
  showIdentity,
  canRemove,
  removing,
  onRemove,
  children,
}: {
  item: Entry;
  showIdentity: boolean;
  canRemove: boolean;
  removing: boolean;
  onRemove: () => void;
  children?: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const date = item.war_end
    ? new Date(item.war_end).toLocaleDateString(undefined, {
        month: "numeric",
        day: "numeric",
      })
    : "Date unavailable";
  const opponent =
    item.source === "manual"
      ? "Manual"
      : `vs ${item.opponent_name || "Unknown opponent"}`;

  const expires = item.expires_at ? new Date(item.expires_at) : null;
  const validExpiry =
    expires && Number.isFinite(expires.getTime()) ? expires : null;
  const days = validExpiry
    ? Math.max(0, Math.ceil((validExpiry.getTime() - Date.now()) / 86400000))
    : null;
  const Icon =
    item.status === "removed"
      ? XCircle
      : item.status === "expired"
        ? Clock3
        : item.status === "exempt"
          ? ShieldCheck
          : item.kind === "strike"
            ? MinusCircle
            : CheckCircle2;
  return (
    <article className={`strike-compact-row ${item.status}`}>
      <div className="strike-compact-copy">
        {showIdentity && (
          <strong className="strike-war-player">
            {item.player_name} · {item.player_tag}
          </strong>
        )}
        <span className="strike-compact-facts">
          <time dateTime={item.war_end || undefined}>{date}</time>
          {" · "}
          {opponent}
          {item.reason && <> · {item.reason}</>}
          {" · "}
          <span className="strike-inline-status">
            <Icon size={13} aria-hidden="true" />
            {statusText(item)}
          </span>
          {item.status === "active" && item.kind === "strike" && (
            <span title={validExpiry?.toLocaleString()}>
              {" · "}
              {days === null
                ? "Expiry unavailable"
                : `expires in ${days} ${days === 1 ? "day" : "days"}`}
            </span>
          )}
        </span>
      </div>
      <button
        className="strike-row-more"
        aria-label={`Details and actions for ${date} ${opponent}`}
        aria-expanded={expanded || removing}
        onClick={() => setExpanded((value) => !value)}
      >
        ⋯
      </button>
      {(expanded || removing) && (
        <div className="strike-row-details">
          <p>
            {item.source_label ||
              (item.source === "manual"
                ? "Manual strike"
                : "Source unavailable")}
            {item.war_clan_name ? ` · ${item.war_clan_name}` : ""}
          </p>
          <p>
            Recorded:{" "}
            {item.war_end
              ? new Date(item.war_end).toLocaleString()
              : "Unavailable"}
          </p>
          {validExpiry && (
            <p>
              Expires:{" "}
              <time dateTime={item.expires_at!}>
                {validExpiry.toLocaleString()}
              </time>
            </p>
          )}
          {showIdentity && (
            <p>
              {strikeLinkLabel(
                item.discord_id,
                item.discord_name,
                item.link_status,
              )}{" "}
              · {item.current_clan_name || "Current clan unavailable"}
            </p>
          )}
          {item.war_plan_reason && <p>{item.war_plan_reason}</p>}
          {item.removed_reason && <p>Removed: {item.removed_reason}</p>}
          {item.exemption && <p>Exemption: {item.exemption}</p>}
          {canRemove && !removing && (
            <button onClick={onRemove}>Remove strike</button>
          )}
          {removing && children}
        </div>
      )}
    </article>
  );
}
