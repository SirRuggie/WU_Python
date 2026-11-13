import type { Season } from "./api";
import { exportMonthLabel } from "./exportPreview";

type SeasonLabel = Pick<Season, "label" | "cwl_month">;

const validMonth = (value: string | null | undefined) =>
  value && /^\d{4}-(0[1-9]|1[0-2])$/.test(value) ? value : "";
export const seasonCycle = (season: SeasonLabel) =>
  validMonth(season.cwl_month) || validMonth(season.label);
export const seasonMonthLabel = (season: SeasonLabel) =>
  exportMonthLabel(seasonCycle(season) || season.label);
export function monthSeasons<T extends SeasonLabel & { id: number }>(
  seasons: readonly T[],
): T[] {
  return [...seasons].sort(
    (a, b) => seasonCycle(b).localeCompare(seasonCycle(a)) || b.id - a.id,
  );
}

export function defaultStaffSeason(
  seasons: readonly (SeasonLabel & Pick<Season, "id" | "history_only">)[],
): string {
  const ordered = monthSeasons(seasons);
  const season =
    ordered.find(
      (row) => row.history_only !== true && row.history_only !== 1,
    ) ?? ordered[0];
  return String(season?.id ?? "");
}
