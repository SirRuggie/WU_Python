import "./ClanWeightSource.css";
import { useDashboardPermission } from "./DashboardPermissions";

/** Use the app's guarded navigation, including when an editor has unsaved inputs. */
export default function ClanWeightSource({
  onNavigate,
  account,
}: {
  onNavigate?: (player?: string, clan?: string) => void;
  account?: {
    tag: string;
    clan_weight_managed?: boolean;
    clan_weight_clan_name?: string | null;
    clan_weight_clan_tag?: string | null;
    clan_weight_saved_at?: string | null;
    current_fwa_clan_tag?: string | null;
  };
}) {
  const allowed = useDashboardPermission("clan_weights");
  const params = new URLSearchParams();
  if (account) params.set("player", account.tag);
  if (account?.current_fwa_clan_tag)
    params.set("clan", account.current_fwa_clan_tag);
  return (
    <div className="clan-weight-source">
      {allowed ? (
        <>
          <span>
            {account?.clan_weight_saved_at
              ? `Saved in ${account.clan_weight_clan_name || account.clan_weight_clan_tag} · ${new Date(account.clan_weight_saved_at).toLocaleDateString()}`
              : account?.current_fwa_clan_tag && !account.clan_weight_managed
                ? "Set this FWA player's weight in Clan weights"
                : "Weight comes from Clan weights"}
          </span>{" "}
          <a
            href={`/clan-weights${params.size ? `?${params}` : ""}`}
            onClick={(event) => {
              if (
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              )
                return;
              if (onNavigate) {
                event.preventDefault();
                onNavigate(
                  account?.tag,
                  account?.current_fwa_clan_tag || undefined,
                );
              }
            }}
          >
            Open Clan weights →
          </a>
        </>
      ) : (
        "Weight comes from Clan weights. Ask a staff member with Clan weights access."
      )}
    </div>
  );
}
