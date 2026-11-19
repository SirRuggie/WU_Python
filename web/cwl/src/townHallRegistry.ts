import { api } from "./api";

export type TownHallEntry = { level: number; emoji_url: string | null };
let loaded: ReadonlyMap<number, string | null> | null = null;
let pending: Promise<ReadonlyMap<number, string | null>> | null = null;

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

export function knownTownHallIcon(level: number | null | undefined) {
  return level == null ? null : loaded?.get(level) || null;
}
