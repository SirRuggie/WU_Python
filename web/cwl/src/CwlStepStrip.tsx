import { useDashboardPermission } from "./DashboardPermissions";
import type { PublicationDraft } from "./publication";
import "./CwlStepStrip.css";

export default function CwlStepStrip({
  step,
  draft,
  onBuild,
  onFinalize,
  onAnnounce,
}: {
  step: "build" | "review" | "announce";
  draft: PublicationDraft | null;
  onBuild: () => void;
  onFinalize: () => void;
  onAnnounce: () => void;
}) {
  const roster = useDashboardPermission("cwl_roster");
  const signups = useDashboardPermission("cwl_signups");
  const publish = useDashboardPermission("cwl_publish");
  const send = useDashboardPermission("cwl_send");
  return (
    <nav className="cwl-step-strip roster-ui" aria-label="CWL workflow">
      {(roster || signups) && (
        <button
          aria-current={step === "build" ? "step" : undefined}
          onClick={onBuild}
        >
          1 Build
        </button>
      )}
      {publish && (
        <button
          aria-current={step === "review" ? "step" : undefined}
          onClick={onFinalize}
        >
          2 Finalize
          {draft?.draft_changed ||
          (!draft?.published && (draft?.preview.assigned_count ?? 0) > 0) ? (
            <span className="cwl-step-changes" aria-label="Unpublished changes">
              {" "}
              ●
            </span>
          ) : draft?.published ? (
            <span aria-label="Published and current"> ✓</span>
          ) : null}
        </button>
      )}
      {send && (
        <button
          aria-current={step === "announce" ? "step" : undefined}
          onClick={onAnnounce}
        >
          3 Announce
        </button>
      )}
    </nav>
  );
}
