import DashboardLink from "./DashboardLink";
import { dashboardPath, type DashboardRoute } from "./dashboardHistory";

/** One read-only destination cue, placed at the end of each CWL page. */
export default function CwlNextLink({
  label,
  route,
  onNext,
  disabled = false,
}: {
  label: string;
  route: Pick<DashboardRoute, "view" | "season" | "step">;
  onNext?: () => void;
  disabled?: boolean;
}) {
  if (!onNext) return null;
  return (
    <DashboardLink
      className="button cwl-next-cue"
      href={dashboardPath(route)}
      disabled={disabled}
      onNavigate={onNext}
    >
      Next: {label} ›
    </DashboardLink>
  );
}
