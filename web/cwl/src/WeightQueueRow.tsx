import { usesClanWeights } from "./clanWeightPolicy";
import type { Ref } from "react";
import ClanWeightSource from "./ClanWeightSource";
import TownHallIcon from "./TownHallIcon";
import CompactWeightField from "./CompactWeightField";
import type { ManualWeightDraft } from "./manualWeight";
import type { RosterAccount } from "./roster";

export default function WeightQueueRow({
  account,
  onClanWeights,
  value,
  onChange,
  disabled,
  busy,
  onEdit,
  onSave,
  inputRef,
  error,
}: {
  account: RosterAccount;
  onClanWeights?: (player?: string, clan?: string) => void;
  value: ManualWeightDraft;
  onChange: (value: ManualWeightDraft) => void;
  disabled: boolean;
  busy: boolean;
  onEdit: (tag: string) => void;
  onSave: () => void;
  inputRef: Ref<HTMLInputElement>;
  error?: string;
}) {
  return (
    <form
      className="weight-queue-row"
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      <div className="weight-queue-identity">
        <div className="weight-queue-name">
          <TownHallIcon level={account.town_hall} />
          <button
            type="button"
            disabled={busy}
            onClick={() => onEdit(account.tag)}
            title={account.player_name}
          >
            {account.player_name}
          </button>
        </div>
        <div className="weight-queue-meta">
          TH {account.town_hall ?? "—"} · {account.tag} ·{" "}
          {account.pool === "lazy" ? "Lazy" : "Main"} CWL ·{" "}
          {account.source_status === "unavailable"
            ? "FWA source unavailable"
            : "No saved FWA weight"}
        </div>
      </div>
      {usesClanWeights(account) ? (
        <div className="weight-queue-managed">
          {account.clan_weight_managed && !account.current_fwa_clan_tag && (
            <small>Saved player · current FWA membership not confirmed</small>
          )}
          <ClanWeightSource account={account} onNavigate={onClanWeights} />
        </div>
      ) : (
        <CompactWeightField
          value={value}
          onChange={onChange}
          disabled={disabled}
          inputRef={inputRef}
          name={account.player_name}
          error={error}
          showUnitToggle={false}
        />
      )}
    </form>
  );
}
