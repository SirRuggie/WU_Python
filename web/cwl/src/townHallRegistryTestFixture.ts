/** Synthetic preloaded registry for unrelated component/SSR layout unit tests.
 * The real loader/network behavior is covered by TownHallIcon.test.tsx.
 */
export function townHallRegistryTestFixture() {
  const icons = new Map<number, string | null>(
    Array.from({ length: 18 }, (_, index) => {
      const level = index + 2;
      const id = 123456789012345600n + BigInt(level);
      return [level, `https://cdn.discordapp.com/emojis/${id}.webp?size=64`];
    }),
  );
  return {
    knownTownHallIcon: (level: number | null | undefined) =>
      level == null ? null : icons.get(level) || null,
    loadTownHallIcons: async () => icons,
  };
}
