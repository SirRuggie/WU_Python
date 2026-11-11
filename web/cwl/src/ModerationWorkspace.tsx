import { useState } from "react";
import MemberActivityHistory from "./MemberActivityHistory";
import MemberTimeline from "./MemberTimeline";
import ModerationSettings from "./ModerationSettings";
import SectionTabs from "./SectionTabs";
import "./ModerationWorkspace.css";

type Section = "history" | "settings";

export default function ModerationWorkspace({
  onDirty,
  memberId = "",
  onMemberRoute,
}: {
  onDirty?: (dirty: boolean) => void;
  memberId?: string;
  onMemberRoute?: (userId: string) => void;
}) {
  const [section, setSection] = useState<Section>("history");
  const [openedSettings, setOpenedSettings] = useState(false);
  const timeline = !!memberId && section === "history";

  const showSettings = () => {
    setOpenedSettings(true);
    setSection("settings");
  };
  const showHistory = () => {
    setSection("history");
    if (memberId) onMemberRoute?.("");
  };

  return (
    <section
      className="moderation-workspace"
      aria-labelledby="moderation-title"
    >
      <header className="moderation-workspace-heading">
        <div>
          <p className="eyebrow">Server tools</p>
          <h1 id="moderation-title">Moderation</h1>
          <p>Review member events and configure where notices are posted.</p>
        </div>
      </header>
      <SectionTabs
        className="moderation-sections section-tabs--flow"
        label="Moderation sections"
        items={[
          { id: "history", label: "Activity history" },
          { id: "settings", label: "Log settings" },
        ]}
        value={section}
        onChange={(next) =>
          next === "history" ? showHistory() : showSettings()
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
        <div hidden={section !== "settings"}>
          <ModerationSettings onDirty={onDirty} />
        </div>
      )}
    </section>
  );
}
