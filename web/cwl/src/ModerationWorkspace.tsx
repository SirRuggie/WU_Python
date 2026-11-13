import CwlPageHeader from "./CwlPageHeader";
import { useState } from "react";
import { parsePageParam, replacePageParam } from "./pageUrlState";
import MemberActivityHistory from "./MemberActivityHistory";
import MemberTimeline from "./MemberTimeline";
import ModerationSettings from "./ModerationSettings";
import SectionTabs from "./SectionTabs";
import "./ModerationWorkspace.css";

type Section = "history" | "invites" | "channels";

export default function ModerationWorkspace({
  onDirty,
  memberId = "",
  onMemberRoute,
}: {
  onDirty?: (dirty: boolean) => void;
  memberId?: string;
  onMemberRoute?: (userId: string) => void;
}) {
  const [section, setSection] = useState<Section>(
    () =>
      parsePageParam("moderation", "tab", window.location.search) as Section,
  );
  const [openedSettings, setOpenedSettings] = useState(false);
  const timeline = !!memberId && section === "history";

  // Invites and Log channels share one settings load and draft; each tab
  // saves only its own fields.
  const showSettings = (next: "invites" | "channels") => {
    setOpenedSettings(true);
    setSection(next);
    replacePageParam("moderation", "tab", next);
  };
  const showHistory = () => {
    setSection("history");
    replacePageParam("moderation", "tab", "history");
    if (memberId) onMemberRoute?.("");
  };

  return (
    <section
      className="moderation-workspace"
      aria-labelledby="moderation-title"
    >
      <CwlPageHeader
        title={<h1 id="moderation-title">Moderation</h1>}
        description="Review member events and configure where notices are posted."
      />
      <SectionTabs
        className="moderation-sections section-tabs--flow"
        label="Moderation sections"
        items={[
          { id: "history", label: "Activity history" },
          { id: "invites", label: "Invites" },
          { id: "channels", label: "Log channels" },
        ]}
        value={section}
        onChange={(next) =>
          next === "history" ? showHistory() : showSettings(next)
        }
      />
      <div hidden={section !== "history" || timeline}>
        <MemberActivityHistory
          active={section === "history" && !timeline}
          onViewMember={onMemberRoute}
        />
      </div>
      {timeline && (
        <MemberTimeline
          key={memberId}
          userId={memberId}
          onBack={() => onMemberRoute?.("")}
        />
      )}
      {openedSettings && (
        <div hidden={section === "history"}>
          <ModerationSettings
            onDirty={onDirty}
            view={section === "invites" ? "invites" : "channels"}
          />
        </div>
      )}
    </section>
  );
}
