import { api } from "./api";

export type TownHallEntry = {
  level: number;
  emoji_url: string | null;
  weight_max?: number;
};
let loaded: ReadonlyMap<number, string | null> | null = null;
let pending: Promise<ReadonlyMap<number, string | null>> | null = null;
let highestWeightMax: number | null = null;
let highestWeightLevel: number | null = null;

/** One member read per page load, shared by every TownHallIcon instance. */
export function loadTownHallIcons() {
  if (!pending) {
    pending = api<TownHallEntry[]>("/town-halls")
      .then((entries) => {
        const result = new Map<number, string | null>();
        if (Array.isArray(entries)) {
          for (const entry of entries) {
            if (
              !entry ||
              !Number.isInteger(entry.level) ||
              entry.level < 1 ||
              entry.level > 99
            )
              continue;
            const maximum = entry.weight_max;
            if (
              typeof maximum === "number" &&
              Number.isInteger(maximum) &&
              maximum >= 1 &&
              maximum <= 500000 &&
              (highestWeightMax === null || maximum > highestWeightMax)
            ) {
              highestWeightMax = maximum;
              highestWeightLevel = entry.level;
            }
            const url = entry.emoji_url;
            result.set(
              entry.level,
              typeof url === "string" &&
                /^https:\/\/cdn\.discordapp\.com\/emojis\/[0-9]{15,22}\.(webp|gif)\?size=64$/.test(
                  url,
                )
                ? url
                : null,
            );
          }
        }
        loaded = result;
        return result;
      })
      .catch(() => {
        loaded = new Map();
        return loaded;
      });
  }
  return pending;
}

export async function loadTownHallWeightMax(): Promise<{
  level: number;
  max: number;
} | null> {
  await loadTownHallIcons();
  return highestWeightMax === null || highestWeightLevel === null
    ? null
    : { level: highestWeightLevel, max: highestWeightMax };
}

export function knownTownHallIcon(level: number | null | undefined) {
  return level == null ? null : loaded?.get(level) || null;
}
