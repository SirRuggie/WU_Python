import { useDashboardPermission } from "./DashboardPermissions";
import type { PublicationDraft } from "./publication";
import DashboardLink from "./DashboardLink";
import { dashboardPath } from "./dashboardHistory";
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
        <DashboardLink
          key={value}
          href={dashboardPath(
            value === "assignments"
              ? { view: "assignments", season: "" }
              : { view: "signup", season: "", signupPanel: value },
          )}
          aria-label={value === "assignments" ? "My clan assignments" : label}
          aria-current={step === value ? "step" : undefined}
          onNavigate={() => onNavigate(value)}
        >
          {label}
        </DashboardLink>
      ))}
    </nav>
  );
}

export default function CwlStepStrip({
  step,
  draft,
  season = "",
  onBuild,
  onFinalize,
  onAnnounce,
}: {
  step: "build" | "review" | "announce";
  draft: PublicationDraft | null;
  season?: string;
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
        <DashboardLink
          href={dashboardPath({ view: "roster", season })}
          aria-label="Build roster"
          aria-current={step === "build" ? "step" : undefined}
          onNavigate={onBuild}
        >
          1 Build
        </DashboardLink>
      )}
      {publish && (
        <DashboardLink
          href={dashboardPath({ view: "publication", season, step: "review" })}
          aria-label={`Finalize roster${publicationStatus ? ` · ${publicationStatus}` : ""}`}
          aria-current={step === "review" ? "step" : undefined}
          onNavigate={onFinalize}
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
        </DashboardLink>
      )}
      {send && (
        <DashboardLink
          href={dashboardPath({
            view: "publication",
            season,
            step: "announce",
          })}
          aria-label="Announcements"
          aria-current={step === "announce" ? "step" : undefined}
          onNavigate={onAnnounce}
        >
          3 Announce
        </DashboardLink>
      )}
    </nav>
  );
}
