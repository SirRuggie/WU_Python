import type { AnnouncementChannel } from "./announcements";
import type { PreviewPart } from "./DiscordPreview";
export type PingReceipt = {
  test?: boolean;
  token: string;
  actor_id: string;
  state: string;
  created_at: number;
  count: number;
  chunks: number;
  posted: { chunk: number; message_id: string }[];
  attempting: number | null;
  error?: string;
  channel: { id: string; name: string };
};
export type PingState = {
  revision: number;
  channel: { id: string; name: string } | null;
  can_send: boolean;
  channels: (AnnouncementChannel & { can_send: boolean; reason?: string })[];
  warning?: string;
  active: PingReceipt | null;
  test_running: boolean;
  history: PingReceipt[];
  cooldown_until: number;
  test_channel: { id: string; name: string; revision: number };
};
export type PingReview = {
  token: string;
  mode: "live" | "test";
  channel: { id: string; name: string };
  count: number;
  unknown: number;
  unlinked: number;
  chunks: number;
  groups: {
    tag: string;
    name: string;
    accounts: { tag: string; name: string }[];
    unlinked: { tag: string; name: string }[];
    users: string[];
  }[];
  previews: PreviewPart[][];
};
