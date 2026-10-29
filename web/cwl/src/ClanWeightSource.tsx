import "./ClanWeightSource.css";
import { useDashboardPermission } from "./DashboardPermissions";

/** Use the app's guarded navigation, including when an editor has unsaved inputs. */
export default function ClanWeightSource({
  onNavigate,
}: {
  onNavigate?: () => void;
}) {
  const allowed = useDashboardPermission("clan_weights");
  return (
    <div className="clan-weight-source">
      {allowed ? (
        <>
          <span>Weight comes from Clan weights</span>{" "}
          <a
            href="/clan-weights"
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
                onNavigate();
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
