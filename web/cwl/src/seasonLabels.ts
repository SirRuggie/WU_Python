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
