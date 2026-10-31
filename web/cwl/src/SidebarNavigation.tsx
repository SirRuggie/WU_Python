import DashboardIcon, { type DashboardIconName } from "./DashboardIcon";
import { useEffect, useRef, useState } from "react";

export const dashboardViews = [
  "weight-trial",
  "search",
  "wars",
  "events",
  "declaration",
  "image-gallery",
  "tickets",
  "staff-overview",
  "clan-management",
  "strikes",
  "replacements",
  "members-settings",
  "member-activity",
  "moderation",
  "applications-settings",
  "fwa-settings",
  "connections-settings",
  "cwl-returns",
  "text-commands",
  "manage",
  "reminders",
  "todo",
  "home",
  "exports",
  "signup",
  "assignments",
  "roster",
  "publication",
  "participation",
  "bonuses",
  "staff",
  "access",
  "issues",
] as const;
export type DashboardView = (typeof dashboardViews)[number];
type Item = {
  signupPanel?: "register" | "saved";
  step?: "review" | "announce";
  view: DashboardView;
  label: string;
  icon: DashboardIconName;
  access?: "owner";
  permissions?: string[];
};
type Section = {
  id: string;
  label: string;
  icon: DashboardIconName;
  items: Item[];
  access?: "staff" | "owner";
  direct?: boolean;
};

// Keep each destination's existing grant list and route id.
const sections: Section[] = [
  {
    id: "my-dashboard",
    label: "Home",
    icon: "home",
    direct: true,
    items: [
      { view: "home", label: "Home", icon: "home" },
      { view: "search", label: "Search", icon: "search" },
    ],
  },
  {
    id: "activity",
    label: "Activity",
    icon: "tasks",
    direct: true,
    items: [
      { view: "todo", label: "Tasks", icon: "tasks" },
      { view: "wars", label: "Wars", icon: "war" },
      { view: "events", label: "Events", icon: "calendar" },
    ],
  },
  {
    id: "my-cwl",
    label: "My CWL",
    icon: "trophy",
    items: [
      {
        view: "signup",
        signupPanel: "register",
        label: "Sign up",
        icon: "signup",
      },
      {
        view: "signup",
        signupPanel: "saved",
        label: "My signups",
        icon: "signedUp",
      },
      { view: "assignments", label: "My clan assignments", icon: "castle" },
    ],
  },
  {
    id: "staff-overview",
    label: "Staff overview",
    icon: "overview",
    direct: true,
    items: [
      {
        view: "staff-overview",
        label: "Staff overview",
        icon: "overview",
        permissions: [
          "cwl",
          "cwl_signups",
          "cwl_roster",
          "cwl_publish",
          "cwl_reminders",
          "cwl_results",
          "cwl_bonuses",
          "cwl_send",
          "cwl_settings",
          "clan_weights",
          "clans",
          "text_commands",
          "recruitment",
          "tickets",
          "member_roles",
          "fwa",
          "server_tools",
        ],
      },
    ],
  },
  {
    id: "cwl",
    label: "CWL",
    icon: "crown",
    access: "staff",
    items: [
      {
        view: "staff",
        permissions: ["cwl_settings"],
        label: "Seasons",
        icon: "seasonSettings",
      },
      {
        view: "reminders",
        permissions: ["cwl_reminders"],
        label: "Signup reminders",
        icon: "bell",
      },
      {
        view: "roster",
        permissions: ["cwl_roster", "cwl_signups"],
        label: "Build roster",
        icon: "roster",
      },
      {
        view: "publication",
        step: "review",
        permissions: ["cwl_publish"],
        label: "Finalize roster",
        icon: "publish",
      },
      {
        view: "publication",
        step: "announce",
        permissions: ["cwl_send"],
        label: "Announcements",
        icon: "megaphone",
      },
      {
        view: "declaration",
        permissions: ["cwl_roster"],
        label: "Declaration check",
        icon: "readiness",
      },
      {
        view: "cwl-returns",
        permissions: ["cwl_reminders"],
        label: "Return reminders",
        icon: "return",
      },
      {
        view: "participation",
        permissions: ["cwl_results"],
        label: "Results & participation",
        icon: "results",
      },
      {
        view: "bonuses",
        permissions: ["cwl_bonuses", "cwl_send"],
        label: "Bonus medals",
        icon: "medal",
      },
      {
        view: "exports",
        permissions: ["cwl_results"],
        label: "Exports & history",
        icon: "download",
      },
    ],
  },
  {
    id: "moderation",
    label: "Moderation",
    icon: "moderation",
    direct: true,
    items: [
      {
        view: "moderation",
        label: "Moderation",
        icon: "moderation",
        permissions: ["member_roles"],
      },
    ],
  },
  {
    id: "clans",
    label: "Clans",
    icon: "shield",
    items: [
      {
        view: "clan-management",
        label: "Family clans",
        icon: "family",
        permissions: ["clans"],
      },
      {
        view: "weight-trial",
        label: "Clan weights",
        icon: "weights",
        permissions: ["clan_weights"],
      },
      {
        view: "strikes",
        label: "Strikes & replacements",
        icon: "flag",
        permissions: ["strikes", "strikes_add", "strikes_remove"],
      },
      {
        view: "fwa-settings",
        label: "FWA tools",
        icon: "fwa",
        permissions: ["fwa"],
      },
    ],
  },
  {
    id: "members",
    label: "Members",
    icon: "users",
    items: [
      {
        view: "members-settings",
        label: "Members & roles",
        icon: "memberRoles",
        permissions: ["member_roles"],
      },
      {
        view: "tickets",
        label: "Tickets",
        icon: "ticket",
        permissions: ["tickets"],
      },
      {
        view: "applications-settings",
        label: "Ticket settings",
        icon: "ticketSettings",
        permissions: ["recruitment", "tickets"],
      },
    ],
  },
  {
    id: "bot",
    label: "Bot",
    icon: "bot",
    items: [
      {
        view: "text-commands",
        label: "Command triggers",
        icon: "command",
        permissions: ["text_commands"],
      },
      {
        view: "image-gallery",
        label: "Image gallery",
        icon: "image",
        permissions: ["text_commands"],
      },
      {
        view: "connections-settings",
        label: "Integrations",
        icon: "connect",
        permissions: ["server_tools"],
      },
    ],
  },
  {
    id: "admin",
    label: "Admin",
    icon: "admin",
    access: "owner",
    items: [
      {
        view: "access",
        label: "Staff access",
        icon: "staffAccess",
        access: "owner",
      },
      {
        view: "issues",
        label: "Dashboard issues",
        icon: "issues",
        access: "owner",
      },
    ],
  },
];
// Navigation mirrors explicit grants; every API still checks authorization.
export function visibleNavigationSections(
  canEdit: boolean,
  isOwner: boolean,
  permissions: string[] = [],
) {
  return sections
    .filter(
      (section) =>
        !section.access || (section.access === "staff" ? canEdit : isOwner),
    )
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) =>
          (item.access !== "owner" || isOwner) &&
          (isOwner ||
            !item.permissions ||
            item.permissions.some(
              (scope) =>
                permissions.includes(scope) ||
                (scope.startsWith("cwl_") && permissions.includes("cwl")),
            )),
      ),
    }))
    .filter((section) => section.items.length > 0);
}
export function navigationLabel(
  view: DashboardView,
  step: "review" | "announce" = "review",
): string {
  if (view === "publication")
    return step === "announce" ? "Announcements" : "Finalize roster";
  if (view === "member-activity") return "Moderation";
  return (
    sections
      .flatMap((section) => section.items)
      .find(
        (item) => item.view === (view === "replacements" ? "strikes" : view),
      )?.label || (view === "manage" ? "Server management" : "Dashboard")
  );
}
export function navigationSection(view: DashboardView) {
  if (view === "staff-overview" || view === "moderation") return "Staff tools";
  if (view === "member-activity") return navigationSection("moderation");
  return sections.find((section) =>
    section.items.some(
      (item) => item.view === (view === "replacements" ? "strikes" : view),
    ),
  )?.label;
}
const memberSectionIds = new Set(["my-dashboard", "activity", "my-cwl"]);
const preferenceIds = new Set([
  "my-dashboard",
  "activity",
  "my-cwl",
  "cwl",
  "clans",
  "members",
  "bot",
  "admin",
]);

export default function SidebarNavigation({
  userId,
  view,
  canEdit,
  isOwner,
  permissions = [],
  onNavigate,
  publicationStep = "review",
  onPublication,
  signupPanel = "register",
  onSignup,
  tourExpanded = false,
}: {
  userId: string;
  view: DashboardView;
  canEdit: boolean;
  isOwner: boolean;
  permissions?: string[];
  onNavigate: (view: DashboardView) => void;
  publicationStep?: "review" | "announce";
  onPublication?: (step: "review" | "announce") => void;
  signupPanel?: "register" | "saved";
  onSignup?: (panel: "register" | "saved") => void;
  tourExpanded?: boolean;
}) {
  const key = `wu-navigation-v3:${userId}`;
  const cwlToggled = useRef(false);
  const preferences = useRef<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    let carried: Record<string, boolean> = {};
    try {
      const current = localStorage.getItem(key);
      const parsed = JSON.parse(
        current || localStorage.getItem(`wu-navigation-v2:${userId}`) || "{}",
      );
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        carried = Object.fromEntries(
          Object.entries(parsed).filter(
            ([id, value]) =>
              preferenceIds.has(id) &&
              typeof value === "boolean" &&
              (id !== "my-cwl" || current !== null),
          ),
        ) as Record<string, boolean>;
      }
      cwlToggled.current = typeof carried["my-cwl"] === "boolean";
    } catch {
      /* Preferences are optional. */
    }
    const initial = Object.fromEntries(
      [...preferenceIds].map((id) => [
        id,
        typeof carried[id] === "boolean"
          ? carried[id]
          : id === "my-dashboard" || id === "my-cwl",
      ]),
    ) as Record<string, boolean>;
    preferences.current = { ...initial };
    const active = sections.find((section) =>
      section.items.some(
        (item) => item.view === (view === "replacements" ? "strikes" : view),
      ),
    );
    if (active && !active.direct && active.id !== "my-cwl")
      initial[active.id] = true;
    return initial;
  });

  useEffect(() => {
    if (tourExpanded) return;
    const active = sections.find((section) =>
      section.items.some(
        (item) => item.view === (view === "replacements" ? "strikes" : view),
      ),
    );
    if (active && !active.direct && active.id !== "my-cwl") {
      setExpanded((current) =>
        current[active.id] ? current : { ...current, [active.id]: true },
      );
    }
  }, [view, tourExpanded]);

  useEffect(() => {
    try {
      const saved = { ...preferences.current };
      if (!cwlToggled.current) delete saved["my-cwl"];
      localStorage.setItem(key, JSON.stringify(saved));
    } catch {
      /* Preferences are optional. */
    }
  }, [expanded, key]);

  const itemActive = (item: Item) =>
    (view === "replacements" ? "strikes" : view) === item.view &&
    (!item.step || item.step === publicationStep) &&
    (!item.signupPanel || item.signupPanel === signupPanel);
  const itemButton = (item: Item) => (
    <button
      data-tour-target={item.signupPanel || item.view}
      key={`${item.view}:${item.step || item.signupPanel || ""}`}
      aria-current={itemActive(item) ? "page" : undefined}
      onClick={() =>
        item.signupPanel && onSignup
          ? onSignup(item.signupPanel)
          : item.step && onPublication
            ? onPublication(item.step)
            : onNavigate(item.view)
      }
    >
      <span className="navigation-icon" aria-hidden="true">
        <DashboardIcon name={item.icon} />
      </span>
      <span>{item.label}</span>
    </button>
  );
  const visible = visibleNavigationSections(canEdit, isOwner, permissions);
  const memberSections = visible.filter((section) =>
    memberSectionIds.has(section.id),
  );
  const staffSections = visible.filter(
    (section) => !memberSectionIds.has(section.id),
  );

  const renderSection = (section: Section) => {
    if (section.direct)
      return (
        <section
          className="navigation-section navigation-everyday"
          key={section.id}
        >
          {section.id === "activity" && (
            <h2 className="navigation-label">Activity</h2>
          )}
          {section.items.map(itemButton)}
        </section>
      );
    const active = section.items.some(
      (item) => item.view === (view === "replacements" ? "strikes" : view),
    );
    const shown = tourExpanded ? active : !!expanded[section.id];
    return (
      <section
        className={`navigation-section${active ? " contains-current" : ""}`}
        key={section.id}
      >
        <button
          className="navigation-toggle"
          aria-expanded={shown}
          aria-controls={`navigation-${section.id}`}
          onClick={() => {
            if (section.id === "my-cwl") cwlToggled.current = true;
            preferences.current[section.id] = !expanded[section.id];
            setExpanded((current) => ({
              ...current,
              [section.id]: !current[section.id],
            }));
          }}
        >
          <span className="navigation-icon" aria-hidden="true">
            <DashboardIcon name={section.icon} />
          </span>
          <span>{section.label}</span>
          <span className="navigation-chevron" aria-hidden="true">
            <DashboardIcon name={shown ? "chevronDown" : "chevronRight"} />
          </span>
        </button>
        <div
          id={`navigation-${section.id}`}
          className="navigation-children"
          hidden={!shown}
        >
          {section.items.map(itemButton)}
        </div>
      </section>
    );
  };

  return (
    <nav aria-label="Warriors United navigation">
      {memberSections.map(renderSection)}
      {staffSections.length > 0 && (
        <div className="navigation-staff">
          <h2 className="navigation-label navigation-staff-label">
            Staff tools
          </h2>
          {staffSections.map(renderSection)}
        </div>
      )}
    </nav>
  );
}
