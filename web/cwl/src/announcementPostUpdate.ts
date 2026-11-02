import type { PreviewPart } from "./DiscordMessagePreview";
import type { ManageButton } from "./manageBridge";
export type PostCopy = { title: string; body: string; buttons: ManageButton[] };
export type PostReview = {
  status:
    | "pending_preview"
    | "previewing"
    | "ready"
    | "pending_update"
    | "updating"
    | "done"
    | "failed"
    | "uncertain"
    | "expired";
  candidate: PostCopy;
  generation: string;
  future_months: boolean;
  worker_ready: boolean;
  has_changes?: boolean;
  channel_name?: string | null;
  message_url?: string | null;
  error?: string;
  error_code?: string;
  live_preview?: PreviewPart[];
  draft_preview?: PreviewPart[];
  campaign_saved?: boolean;
  recurring_saved?: boolean;
  save_warning?: string;
};
export const postUpdateActive = (state: PostReview | null) =>
  !!state &&
  ["pending_preview", "previewing", "pending_update", "updating"].includes(
    state.status,
  );
export function validPostCopy(copy: PostCopy) {
  return (
    !!copy.title.trim() &&
    !!copy.body.trim() &&
    copy.title.length + copy.body.length <= 4000 &&
    copy.buttons.length <= 5 &&
    copy.buttons.every((button) => {
      try {
        const url = new URL(button.url);
        return (
          !!button.label.trim() &&
          button.label.length <= 80 &&
          button.url.length <= 512 &&
          url.protocol === "https:" &&
          !!url.hostname &&
          !url.username &&
          !url.password &&
          !/\s/.test(button.url) &&
          (!button.emoji || button.emoji.length <= 64)
        );
      } catch {
        return false;
      }
    })
  );
}
export function safePostUrl(value?: string | null) {
  return (
    !!value &&
    /^https:\/\/discord\.com\/channels\/[0-9]+\/[0-9]+\/[0-9]+$/.test(value)
  );
}

export function checkedPostReview(value: PostReview): PostReview {
  if (
    !value ||
    typeof value !== "object" ||
    ![
      "pending_preview",
      "previewing",
      "ready",
      "pending_update",
      "updating",
      "done",
      "failed",
      "uncertain",
      "expired",
    ].includes(value.status) ||
    !value.candidate ||
    typeof value.candidate.title !== "string" ||
    typeof value.candidate.body !== "string" ||
    !Array.isArray(value.candidate.buttons) ||
    value.candidate.buttons.some(
      (button) =>
        !button ||
        typeof button.label !== "string" ||
        typeof button.url !== "string",
    ) ||
    typeof value.generation !== "string" ||
    typeof value.worker_ready !== "boolean" ||
    typeof value.future_months !== "boolean" ||
    (value.has_changes !== undefined && typeof value.has_changes !== "boolean")
  )
    throw new Error(
      "The post review is incomplete. Refresh its status before updating.",
    );
  return value;
}
