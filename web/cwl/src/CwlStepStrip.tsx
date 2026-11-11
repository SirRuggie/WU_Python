import { useDashboardPermission } from "./DashboardPermissions";
import type { PublicationDraft } from "./publication";
import "./CwlStepStrip.css";
import useChoiceRail from "./useChoiceRail";
import "./SectionTabs.css";
import "./ChoiceGroupLayout.css";

export function MemberStepStrip({
  step,
  onNavigate,
}: {
  step: "register" | "saved" | "assignments";
  onNavigate: (step: "register" | "saved" | "assignments") => void;
}) {
  return (
    <nav
      className="cwl-step-strip member-step-strip roster-ui"
      aria-label="My CWL steps"
    >
      {(
        [
          ["register", "Sign up"],
          ["saved", "My signups"],
          ["assignments", "My clan"],
        ] as const
      ).map(([value, label]) => (
        <button
          key={value}
          aria-label={value === "assignments" ? "My clan assignments" : label}
          aria-current={step === value ? "step" : undefined}
          onClick={() => onNavigate(value)}
        >
          {label}
        </button>
      ))}
    </nav>
  );
}

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
  const steps = useChoiceRail<HTMLElement>(step);
  const publicationStatus =
    draft?.draft_changed ||
    (!draft?.published && (draft?.preview.assigned_count ?? 0) > 0)
      ? "Unpublished changes"
      : draft?.published
        ? "Published and current"
        : "";
  return (
    <nav
      {...steps.fadeProps}
      ref={steps.ref}
      className="cwl-step-strip roster-ui section-tabs section-tabs--flow has-horizontal-fades"
      aria-label="CWL workflow"
    >
      {(roster || signups) && (
        <button
          aria-label="Build roster"
          aria-current={step === "build" ? "step" : undefined}
          onClick={onBuild}
        >
          1 Build
        </button>
      )}
      {publish && (
        <button
          aria-label={`Finalize roster${publicationStatus ? ` · ${publicationStatus}` : ""}`}
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
          aria-label="Announcements"
          aria-current={step === "announce" ? "step" : undefined}
          onClick={onAnnounce}
        >
          3 Announce
        </button>
      )}
    </nav>
  );
}
