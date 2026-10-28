import { LockKeyhole } from "lucide-react";
import type { RosterAccount } from "./roster";

export default function PlayerCardMeta({
  account,
  showPool = true,
  id,
  className = "",
}: {
  account: RosterAccount;
  showPool?: boolean;
  id?: string;
  className?: string;
}) {
  const pool =
    showPool && account.pool
      ? account.pool === "main"
        ? "Main"
        : "Lazy"
      : null;
  return (
    <span id={id} className={`player-card-meta ${className}`}>
      <span className="player-card-meta-core" aria-hidden="true">
        TH{account.town_hall ?? "—"} · {account.tag}
      </span>
      {pool && (
        <span
          className="player-card-meta-pool"
          aria-hidden="true"
          title={`${pool} CWL`}
        >
          · {pool}
        </span>
      )}
      {account.kept && (
        <LockKeyhole
          size={13}
          aria-label="Locked placement"
          aria-hidden="true"
        />
      )}
      <span className="sr-only">
        Town Hall {account.town_hall ?? "unknown"}. {account.tag}.
        {pool ? ` ${pool} CWL.` : ""}
        {account.kept ? " Locked placement." : ""}
      </span>
    </span>
  );
}
