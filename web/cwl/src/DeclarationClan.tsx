import { useState } from "react";
import { Button } from "./rosterUi/primitives";
import {
  declarationMentions,
  type declarationGroups,
} from "./declarationGroups";
import DeclarationPlayerCard from "./DeclarationPlayerCard";
import type { LocationRecords } from "./comparisonLocation";
import type { StaffDetailsRequest } from "./staffDetailsRequest";
export default function DeclarationClan({
  group,
  open,
  onToggle,
  records,
  now,
  request,
  search,
}: {
  group: ReturnType<typeof declarationGroups>[number];
  open: boolean;
  onToggle: () => void;
  records: LocationRecords;
  now: number;
  request: Omit<StaffDetailsRequest, "tag">;
  search: string;
}) {
  const [copied, setCopied] = useState("");
  const [fallback, setFallback] = useState<string | null>(null);
  const mentions = declarationMentions(group.late);
  const { ready, arrivedCount, needed, refreshToConfirm } = group.readiness;
  const panelId = `declaration-${group.key.replace(/[^a-zA-Z0-9]/g, "-")}`;
  async function copy() {
    setCopied("");
    setFallback(null);
    try {
      await navigator.clipboard.writeText(mentions.text);
      setCopied(`Copied ${mentions.count} mentions`);
    } catch {
      setFallback(mentions.text);
    }
  }
  return (
    <section
      className={`declaration-clan ${!group.tag ? "is-unassigned" : ready ? "is-ready" : "is-not-ready"}`}
    >
      <h2>
        <button
          type="button"
          className="declaration-clan-toggle"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
        >
          <span>
            <span aria-hidden="true">{open ? "▾" : "›"}</span> {group.name}
          </span>
          <span>
            {!group.tag
              ? `${group.accounts.length} awaiting placement`
              : `${ready ? "Ready" : "Not ready"} · ${arrivedCount}/${group.capacity ?? "—"} in clan`}
          </span>
          {group.tag && (
            <small>
              {group.capacity === null
                ? "War size not set"
                : ready || needed === 0
                  ? `${group.capacity}v${group.capacity}`
                  : `needs ${needed} for ${group.capacity}v${group.capacity}`}
              {refreshToConfirm ? " · Refresh to confirm" : ""}
            </small>
          )}
        </button>
      </h2>
      {group.tag && group.capacity === null && (
        <a
          className="declaration-settings"
          href={`/cwl/roster?season=${request.seasonId}`}
          onClick={() => {
            try {
              sessionStorage.setItem(
                `wu-roster-${request.seasonId}-mode`,
                JSON.stringify("rules"),
              );
            } catch {
              /* Optional view preference. */
            }
          }}
        >
          Clan settings ›
        </a>
      )}
      {open && (
        <div id={panelId} className="declaration-clan-content">
          {group.tag && !ready && (
            <div className="declaration-copy">
              <Button onClick={() => void copy()} disabled={!mentions.count}>
                Copy mentions
              </Button>
              {!!mentions.unlinked.length && (
                <small>Can't mention: {mentions.unlinked.join(", ")}</small>
              )}
              <span role="status">{copied}</span>
              {fallback !== null && (
                <label>
                  Copy these mentions
                  <textarea
                    readOnly
                    value={fallback}
                    onFocus={(e) => e.currentTarget.select()}
                  />
                </label>
              )}
            </div>
          )}
          {group.accounts.map((account) => (
            <DeclarationPlayerCard
              key={account.tag}
              account={account}
              clanName={group.name}
              record={records[account.tag]}
              now={now}
              request={{ ...request, order: group.accounts.map((a) => a.tag) }}
              highlighted={
                !!search &&
                [account.player_name, account.tag, group.name].some((s) =>
                  s.toLowerCase().includes(search),
                )
              }
            />
          ))}
        </div>
      )}
    </section>
  );
}
