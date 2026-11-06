import { api, ApiError } from "./api";

export type ModerationKind =
  | "join"
  | "leave"
  | "kick"
  | "ban"
  | "member_update"
  | "timeout_add"
  | "timeout_remove"
  | "link"
  | "invite_create"
  | "invite_delete"
  | "invite_use";
export type CategoryKind = "members" | "moderation" | "messages" | "invites";
const categoryKinds: CategoryKind[] = [
  "members",
  "moderation",
  "messages",
  "invites",
];
const moderationKinds: ModerationKind[] = [
  "join",
  "leave",
  "kick",
  "ban",
  "member_update",
  "timeout_add",
  "timeout_remove",
  "link",
  "invite_create",
  "invite_delete",
  "invite_use",
];
export type RouteTarget = {
  channel_id: string | null;
  forum_tag_id: string | null;
};
export type CategoryConfig = RouteTarget & {
  mode: "main" | "own" | "off";
};
export type EventConfig = RouteTarget & {
  enabled: boolean;
};
export type EventSettings = Record<ModerationKind, EventConfig>;
export type CategorySettings = Record<CategoryKind, CategoryConfig>;
export type LinkIgnores = { channel_ids: string[]; role_ids: string[] };
export type SettingsDraft = {
  main: RouteTarget;
  categories: CategorySettings;
  events: EventSettings;
  ignores: LinkIgnores;
  invite_names: Record<string, string>;
};
export type InviteRow = {
  code: string;
  name: string | null;
  inviter_id: string | null;
  inviter_name: string | null;
  channel_id: string | null;
  channel_name: string | null;
  uses: number;
  max_uses: number | null;
  expires_at: string | null;
  vanity: boolean;
};
export type InvitesResponse = {
  invites: InviteRow[];
  updated_at: string | null;
};
export type Destination = {
  id: string;
  name: string;
  type: "text" | "forum" | "forum_post";
  available_tags: { id: string; name: string; moderated: boolean }[];
  can_post: boolean;
  requires_tag: boolean;
  can_manage_threads: boolean;
};
export type SettingsResponse = SettingsDraft & {
  schema_version: 2;
  revision: number;
  channels?: Destination[] | null;
  channels_available?: boolean;
  warning?: string | null;
  preview_names?: Record<string, string>;
  preview_cards?: Partial<Record<ModerationKind, unknown>>;
  forum_preview_cards?: Partial<Record<ModerationKind, unknown>>;
};

type RegistryEvent = {
  key: string;
  label: string;
  icon: string;
  color: string;
  explanation: string;
  supported: boolean;
};
export const moderationRegistry: {
  key: CategoryKind | "server";
  label: string;
  icon: string;
  events: RegistryEvent[];
}[] = [
  {
    key: "members",
    label: "Members",
    icon: "👥",
    events: [
      {
        key: "join",
        label: "Joins",
        icon: "👋",
        color: "#2ba66a",
        explanation: "Member joins the server.",
        supported: true,
      },
      {
        key: "leave",
        label: "Leaves",
        icon: "🚪",
        color: "#d34a4a",
        explanation: "Member leaves the server.",
        supported: true,
      },
      {
        key: "member_update",
        label: "Profile changes",
        icon: "✏️",
        color: "#398fc9",
        explanation: "Nickname, name or avatar changes.",
        supported: true,
      },
      {
        key: "roles_added",
        label: "Roles added",
        icon: "🏷️",
        color: "#398fc9",
        explanation: "",
        supported: false,
      },
      {
        key: "roles_removed",
        label: "Roles removed",
        icon: "🏷️",
        color: "#398fc9",
        explanation: "",
        supported: false,
      },
    ],
  },
  {
    key: "moderation",
    label: "Moderation",
    icon: "🛡️",
    events: [
      {
        key: "kick",
        label: "Kicks",
        icon: "👢",
        color: "#e69935",
        explanation: "Verified member kick.",
        supported: true,
      },
      {
        key: "ban",
        label: "Bans",
        icon: "🔨",
        color: "#a8384b",
        explanation: "Verified member ban.",
        supported: true,
      },
      {
        key: "unban",
        label: "Unbans",
        icon: "🔓",
        color: "#2ba66a",
        explanation: "",
        supported: false,
      },
      {
        key: "timeout_add",
        label: "Timeouts",
        icon: "⏱️",
        color: "#e69935",
        explanation: "Member timed out.",
        supported: true,
      },
      {
        key: "timeout_remove",
        label: "Timeout removals",
        icon: "✅",
        color: "#2ba66a",
        explanation: "Timeout removed by a moderator.",
        supported: true,
      },
    ],
  },
  {
    key: "messages",
    label: "Messages",
    icon: "💬",
    events: [
      {
        key: "link",
        label: "Links",
        icon: "🔗",
        color: "#398fc9",
        explanation: "Message with a link.",
        supported: true,
      },
      {
        key: "delete",
        label: "Deletes",
        icon: "🗑️",
        color: "#d34a4a",
        explanation: "",
        supported: false,
      },
      {
        key: "edit",
        label: "Edits",
        icon: "✏️",
        color: "#398fc9",
        explanation: "",
        supported: false,
      },
      {
        key: "bulk_delete",
        label: "Bulk deletes",
        icon: "🗑️",
        color: "#d34a4a",
        explanation: "",
        supported: false,
      },
    ],
  },
  {
    key: "invites",
    label: "Invites",
    icon: "📨",
    events: [
      {
        key: "invite_create",
        label: "Invites created",
        icon: "📨",
        color: "#2ba66a",
        explanation: "Invite created.",
        supported: true,
      },
      {
        key: "invite_delete",
        label: "Invites deleted",
        icon: "🗑️",
        color: "#d34a4a",
        explanation: "Invite deleted.",
        supported: true,
      },
      {
        key: "invite_use",
        label: "Invite uses",
        icon: "🎟️",
        color: "#c9a84f",
        explanation: "Member joins with an invite.",
        supported: true,
      },
    ],
  },
  {
    key: "server",
    label: "Server",
    icon: "🏰",
    events: [
      {
        key: "channel_create",
        label: "Channels created",
        icon: "📚",
        color: "#c9a84f",
        explanation: "",
        supported: false,
      },
      {
        key: "channel_delete",
        label: "Channels deleted",
        icon: "📚",
        color: "#c9a84f",
        explanation: "",
        supported: false,
      },
      {
        key: "channel_change",
        label: "Channels changed",
        icon: "📚",
        color: "#c9a84f",
        explanation: "",
        supported: false,
      },
      {
        key: "role_create",
        label: "Roles created",
        icon: "🏷️",
        color: "#c9a84f",
        explanation: "",
        supported: false,
      },
      {
        key: "role_delete",
        label: "Roles deleted",
        icon: "🏷️",
        color: "#c9a84f",
        explanation: "",
        supported: false,
      },
      {
        key: "role_change",
        label: "Roles changed",
        icon: "🏷️",
        color: "#c9a84f",
        explanation: "",
        supported: false,
      },
    ],
  },
];

export const eventTypes = moderationRegistry.flatMap((category) =>
  category.events
    .filter((event) => event.supported)
    .map((event) => ({
      ...event,
      key: event.key as ModerationKind,
      category: category.key as CategoryKind,
    })),
);

const idPattern = /^\d{17,20}$/;
export const maxIgnoreIds = 100;
export const maxInviteNameLength = 40;

export function normalizeRoleId(value: string): string | null {
  const id = value.trim();
  return idPattern.test(id) ? id : null;
}

function idList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function cloneSettings(settings: SettingsDraft): SettingsDraft {
  const categories = {} as CategorySettings;
  for (const key of categoryKinds) {
    const fallback: CategoryConfig = {
      mode: "main",
      channel_id: null,
      forum_tag_id: null,
    };
    categories[key] = { ...fallback, ...settings.categories?.[key] };
  }
  const events = {} as EventSettings;
  for (const key of moderationKinds) {
    const fallback: EventConfig = {
      enabled: false,
      channel_id: null,
      forum_tag_id: null,
    };
    events[key] = { ...fallback, ...settings.events?.[key] };
  }
  const inviteNames: Record<string, string> = {};
  for (const [code, name] of Object.entries(settings.invite_names || {})) {
    const trimmed = typeof name === "string" ? name.trim() : "";
    if (trimmed) inviteNames[code] = trimmed;
  }
  return {
    main: { ...settings.main },
    categories,
    events,
    ignores: {
      channel_ids: idList(settings.ignores?.channel_ids),
      role_ids: idList(settings.ignores?.role_ids),
    },
    invite_names: inviteNames,
  };
}

export function changedSettings(
  saved: SettingsDraft,
  draft: SettingsDraft,
): boolean {
  return (
    JSON.stringify(cloneSettings(saved)) !==
    JSON.stringify(cloneSettings(draft))
  );
}

export function categoryForEvent(kind: ModerationKind): CategoryKind {
  return (
    eventTypes.find((event) => event.key === kind)?.category || "moderation"
  );
}

export function effectiveDestination(
  settings: SettingsDraft,
  kind: ModerationKind,
): {
  target: RouteTarget | null;
  source: "event" | "category" | "main" | "off";
} {
  const category = settings.categories[categoryForEvent(kind)];
  if (category.mode === "off") return { target: null, source: "off" };
  const event = settings.events[kind];
  if (event.channel_id) {
    return {
      target: {
        channel_id: event.channel_id,
        forum_tag_id: event.forum_tag_id,
      },
      source: "event",
    };
  }
  if (category.mode === "own") {
    return {
      target: {
        channel_id: category.channel_id,
        forum_tag_id: category.forum_tag_id,
      },
      source: "category",
    };
  }
  return { target: settings.main, source: "main" };
}

export function destinationName(
  target: RouteTarget | null,
  channels: Destination[] | null | undefined,
): string {
  if (!target?.channel_id) return "No channel set";
  const channel = channels?.find((item) => item.id === target.channel_id);
  return channel
    ? `#${channel.name}`
    : `Channel ${target.channel_id} (unavailable)`;
}

function invalidTarget(
  target: RouteTarget | null,
  channels: Destination[],
): boolean {
  if (!target?.channel_id) return true;
  const channel = channels.find((item) => item.id === target.channel_id);
  if (!channel?.can_post) return true;
  if (channel.type !== "forum") return false;
  if (channel.requires_tag && !target.forum_tag_id) return true;
  if (!target.forum_tag_id) return false;
  const tag = channel.available_tags.find(
    (item) => item.id === target.forum_tag_id,
  );
  return !tag || (tag.moderated && !channel.can_manage_threads);
}

export function hasInvalidEventDestination(
  settings: SettingsDraft,
  kind: ModerationKind,
  channels: Destination[] | null | undefined,
): boolean {
  if (!channels) return true;
  const { target, source } = effectiveDestination(settings, kind);
  return source !== "off" && invalidTarget(target, channels);
}

export function hasInvalidDestination(
  draft: SettingsDraft,
  channels: Destination[] | null | undefined,
  channelsAvailable = true,
): boolean {
  if (!channelsAvailable || !channels) return true;
  return eventTypes.some(({ key }) => {
    if (!draft.events[key].enabled) return false;
    return hasInvalidEventDestination(draft, key, channels);
  });
}

export function saveModerationSettings(
  saved: SettingsResponse,
  draft: SettingsDraft,
) {
  return api<SettingsResponse>("/manage/member-events/settings", "PUT", {
    revision: saved.revision,
    ...cloneSettings(draft),
  });
}

export function moderationSettingsError(
  cause: unknown,
  operation: "read" | "save" | "test",
) {
  if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
    return {
      denied: true,
      stale: false,
      message:
        "Your staff access has changed. Sign in again or ask an administrator to restore access.",
    };
  }
  if (cause instanceof ApiError && cause.status === 409) {
    return {
      denied: false,
      stale: true,
      message:
        operation === "save"
          ? "These settings changed since you loaded them. Your edits are preserved; reload the latest version before saving again."
          : "Saved settings changed. Refresh before sending a test log.",
    };
  }
  return {
    denied: false,
    stale: false,
    message:
      cause instanceof Error
        ? cause.message
        : operation === "read"
          ? "Could not load moderation settings."
          : operation === "save"
            ? "Could not save moderation settings. Your edits are preserved."
            : "Could not confirm the test log. Check Discord before trying again.",
  };
}
