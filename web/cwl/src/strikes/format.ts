import { formatDate } from "../format";
import { strikeCountLabel } from "../strikeCountLabel";
import type { ImportDraft, ImportResult, Tab } from "./types";

export const tabs: { id: Tab; label: string }[] = [
  { id: "history", label: "Accounts" },
  { id: "leave", label: "Leave" },
  { id: "settings", label: "Settings" },
];
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Could not load data. Try again.";
export const dateText = (value?: string | null) =>
  value
    ? /^\d{4}-\d{2}-\d{2}$/.test(value)
      ? formatDate(new Date(`${value}T00:00:00`))
      : formatDate(new Date(value))
    : "—";
export const importStorageKey = (userId: string) =>
  `wu:strikes:import:${userId}`;
export function savedImport(userId: string): ImportDraft {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(importStorageKey(userId)) || "{}",
    );
    return {
      job:
        value.job &&
        typeof value.job.job_id === "string" &&
        ["preview", "apply"].includes(value.job.phase)
          ? value.job
          : null,
      preview:
        value.preview &&
        typeof value.preview.preview_id === "string" &&
        Array.isArray(value.preview.entries)
          ? value.preview
          : null,
      excluded: Array.isArray(value.excluded)
        ? value.excluded.filter((key: unknown) => typeof key === "string")
        : [],
    };
  } catch {
    return { job: null, preview: null, excluded: [] };
  }
}
export const reviewCount = (count: number) =>
  `${count} ${count === 1 ? "needs" : "need"} review`;
export const importResultText = (result: ImportResult) =>
  `${strikeCountLabel(result.added_strikes ?? result.strikes, "strike")} added · ${result.duplicates ?? (Array.isArray(result.skipped) ? result.skipped.length : result.skipped)} skipped as duplicate · ${result.history_only ?? result.applied - result.strikes} history-only${result.excluded ? ` · ${result.excluded} excluded` : ""}${(result.deferred_count ?? result.deferred_accounts?.length ?? 0) > 0 ? ` · ${reviewCount(result.deferred_count ?? result.deferred_accounts?.length ?? 0)}` : ""}.`;
