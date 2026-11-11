import { api, ApiError } from "./api";
import type { RoleChoice } from "./RolePicker";

export type ModerationKind =
  | "join"
  | "leave"
  | "member_update"
  | "kick"
  | "ban"
  | "unban"
  | "timeout_add"
  | "timeout_remove"
  | "role_create"
  | "role_update"
  | "role_delete"
  | "roles_added"
  | "roles_removed"
  | "link"
  | "message_delete"
  | "message_edit"
  | "message_bulk_delete"
  | "channel_create"
  | "channel_update"
  | "channel_delete"
  | "channel_permissions"
  | "thread_delete"
  | "thread_lock"
  | "server_update"
  | "emoji"
  | "sticker"
  | "app"
  | "webhook"
  | "automod"
  | "invite_create"
  | "invite_delete"
  | "invite_use";
export type CategoryKind =
  | "members"
  | "moderation"
  | "roles"
  | "messages"
  | "channels"
  | "server"
  | "invites";
const categoryKinds: CategoryKind[] = [
  "members",
  "moderation",
  "roles",
  "messages",
  "channels",
  "server",
  "invites",
];
const moderationKinds: ModerationKind[] = [
  "join",
  "leave",
  "member_update",
  "kick",
  "ban",
  "unban",
  "timeout_add",
  "timeout_remove",
  "role_create",
  "role_update",
  "role_delete",
  "roles_added",
  "roles_removed",
  "link",
  "message_delete",
  "message_edit",
  "message_bulk_delete",
  "channel_create",
  "channel_update",
  "channel_delete",
  "channel_permissions",
  "thread_delete",
  "thread_lock",
  "server_update",
  "emoji",
  "sticker",
  "app",
  "webhook",
  "automod",
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
  /** Absent when the backend did not send it; the block is then unavailable. */
  ignored_bot_ids?: string[];
};
export type BotActor = { id: string; name: string; last_seen: string | null };
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
  roles?: RoleChoice[] | null;
  roles_available?: boolean;
  warning?: string | null;
  bot_actors?: BotActor[] | null;
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
  key: CategoryKind;
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
        explanation: "Member unbanned.",
        supported: true,
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
    key: "roles",
    label: "Roles",
    icon: "🏷️",
    events: [
      {
        key: "role_create",
        label: "Roles created",
        icon: "🏷️",
        color: "#2ba66a",
        explanation: "Role created.",
        supported: true,
      },
      {
        key: "role_update",
        label: "Roles updated",
        icon: "🏷️",
        color: "#398fc9",
        explanation: "Role name, color or permissions changed.",
        supported: true,
      },
      {
        key: "role_delete",
        label: "Roles deleted",
        icon: "🏷️",
        color: "#d34a4a",
        explanation: "Role deleted.",
        supported: true,
      },
      {
        key: "roles_added",
        label: "Roles added",
        icon: "➕",
        color: "#398fc9",
        explanation: "Role added to a member.",
        supported: true,
      },
      {
        key: "roles_removed",
        label: "Roles removed",
        icon: "➖",
        color: "#e69935",
        explanation: "Role removed from a member.",
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
        key: "message_delete",
        label: "Deletes",
        icon: "🗑️",
        color: "#d34a4a",
        explanation: "Message deleted.",
        supported: true,
      },
      {
        key: "message_edit",
        label: "Edits",
        icon: "✏️",
        color: "#398fc9",
        explanation: "Message edited.",
        supported: true,
      },
      {
        key: "message_bulk_delete",
        label: "Bulk deletes",
        icon: "🗑️",
        color: "#d34a4a",
        explanation: "Many messages deleted at once.",
        supported: true,
      },
    ],
  },
  {
    key: "channels",
    label: "Channels",
    icon: "📚",
    events: [
      {
        key: "channel_create",
        label: "Channels created",
        icon: "📚",
        color: "#2ba66a",
        explanation: "Channel created.",
        supported: true,
      },
      {
        key: "channel_update",
        label: "Channels updated",
        icon: "📚",
        color: "#398fc9",
        explanation: "Channel name, topic or settings changed.",
        supported: true,
      },
      {
        key: "channel_delete",
        label: "Channels deleted",
        icon: "📚",
        color: "#d34a4a",
        explanation: "Channel deleted.",
        supported: true,
      },
      {
        key: "channel_permissions",
        label: "Permission changes",
        icon: "🔐",
        color: "#e69935",
        explanation: "Channel permissions changed.",
        supported: true,
      },
      {
        key: "thread_delete",
        label: "Threads deleted",
        icon: "🧵",
        color: "#d34a4a",
        explanation: "Thread deleted.",
        supported: true,
      },
      {
        key: "thread_lock",
        label: "Threads locked",
        icon: "🔒",
        color: "#e69935",
        explanation: "Thread locked or archived by a person.",
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
        key: "server_update",
        label: "Server settings",
        icon: "🏰",
        color: "#c9a84f",
        explanation: "Server settings changed.",
        supported: true,
      },
      {
        key: "emoji",
        label: "Emoji",
        icon: "😀",
        color: "#c9a84f",
        explanation: "Emoji added, changed or removed.",
        supported: true,
      },
      {
        key: "sticker",
        label: "Stickers",
        icon: "🏷️",
        color: "#c9a84f",
        explanation: "Sticker added, changed or removed.",
        supported: true,
      },
      {
        key: "app",
        label: "Apps",
        icon: "🧩",
        color: "#c9a84f",
        explanation: "App added, changed or removed.",
        supported: true,
      },
      {
        key: "webhook",
        label: "Webhooks",
        icon: "🪝",
        color: "#c9a84f",
        explanation: "Webhook added, changed or removed.",
        supported: true,
      },
      {
        key: "automod",
        label: "AutoMod rules",
        icon: "🤖",
        color: "#c9a84f",
        explanation: "AutoMod rule added, changed or removed.",
        supported: true,
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

export const maxIgnoreIds = 100;
export const maxIgnoredBots = 50;
export const maxInviteNameLength = 40;
const badNameCharacter = /[\p{Cc}\p{Zl}\p{Zp}]|(?!\u200d)\p{Cf}/u;

/** Same rule as the backend: 1 to 40 characters, no control or separator characters. */
export function inviteNameError(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "";
  if ([...trimmed].length > maxInviteNameLength)
    return `Use at most ${maxInviteNameLength} characters.`;
  if (badNameCharacter.test(trimmed))
    return "Remove control or invisible characters.";
  return "";
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
  const botIds = Array.isArray(settings.ignored_bot_ids)
    ? { ignored_bot_ids: idList(settings.ignored_bot_ids) }
    : {};
  return {
    main: { ...settings.main },
    categories,
    events,
    ignores: {
      channel_ids: idList(settings.ignores?.channel_ids),
      role_ids: idList(settings.ignores?.role_ids),
    },
    invite_names: inviteNames,
    ...botIds,
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

/** One on/off switch. Switches save at once; other edits stay in the draft. */
export type SwitchChange =
  | {
      scope: "category";
      key: CategoryKind;
      values: Pick<CategoryConfig, "mode">;
    }
  | {
      scope: "event";
      key: ModerationKind;
      values: Pick<EventConfig, "enabled">;
    };

export type SwitchFeedback = {
  key: string;
  state: "saving" | "saved" | "draft" | "error";
  message: string;
};
export type SwitchResult = "saving" | "draft" | "ignored";

export function switchKey(change: Pick<SwitchChange, "scope" | "key">) {
  return `${change.scope}:${change.key}`;
}

export function applySwitch(
  settings: SettingsDraft,
  change: SwitchChange,
): SettingsDraft {
  const next = cloneSettings(settings);
  if (change.scope === "category")
    next.categories[change.key] = {
      ...next.categories[change.key],
      ...change.values,
    };
  else
    next.events[change.key] = { ...next.events[change.key], ...change.values };
  return next;
}

/** True when the switch's own category or event has unsaved draft edits. */
export function switchItemEdited(
  saved: SettingsDraft,
  draft: SettingsDraft,
  change: SwitchChange,
): boolean {
  const before = cloneSettings(saved);
  const after = cloneSettings(draft);
  const pair =
    change.scope === "category"
      ? [before.categories[change.key], after.categories[change.key]]
      : [before.events[change.key], after.events[change.key]];
  return JSON.stringify(pair[0]) !== JSON.stringify(pair[1]);
}

/**
 * Keep the draft's unsaved edits on top of newly saved settings. A field the
 * draft did not change takes the new saved value.
 */
export function rebaseDraft(
  oldSaved: SettingsDraft,
  draft: SettingsDraft,
  newSaved: SettingsDraft,
): SettingsDraft {
  const base = cloneSettings(oldSaved);
  const mine = cloneSettings(draft);
  const next = cloneSettings(newSaved);
  const pick = <T>(before: T, edited: T, latest: T): T =>
    JSON.stringify(before) === JSON.stringify(edited) ? latest : edited;
  const categories = {} as CategorySettings;
  for (const key of categoryKinds)
    categories[key] = pick(
      base.categories[key],
      mine.categories[key],
      next.categories[key],
    );
  const events = {} as EventSettings;
  for (const key of moderationKinds)
    events[key] = pick(base.events[key], mine.events[key], next.events[key]);
  const bots = pick(
    base.ignored_bot_ids,
    mine.ignored_bot_ids,
    next.ignored_bot_ids,
  );
  return {
    main: pick(base.main, mine.main, next.main),
    categories,
    events,
    ignores: pick(base.ignores, mine.ignores, next.ignores),
    invite_names: pick(base.invite_names, mine.invite_names, next.invite_names),
    ...(bots ? { ignored_bot_ids: bots } : {}),
  };
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
  return channel ? `#${channel.name}` : "Unavailable channel";
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
  operation: "read" | "save" | "switch" | "test",
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
          : operation === "switch"
            ? "These settings changed since you loaded them. Select Refresh settings, then try again."
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
            : operation === "switch"
              ? "Could not save this switch. Try again."
              : "Could not confirm the test log. Check Discord before trying again.",
  };
}
