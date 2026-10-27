import type { LocationRecords } from "./comparisonLocation";
import type { PublishedComparisonAccount } from "./useComparisonLocations";
export type ComparisonPoolMemory = {
  lastCheck: number;
  checkedAt?: number;
  published: PublishedComparisonAccount[] | null;
  publicationRevision?: number;
  publicationRefresh?: number;
  publicationAt: number;
};
/** Owned by the roster workspace: tab changes preserve it, season changes replace it. */
export function createComparisonMemory() {
  return {
    records: {} as LocationRecords,
    pools: new Map<string, ComparisonPoolMemory>(),
  };
}
export type ComparisonMemory = ReturnType<typeof createComparisonMemory>;
export function comparisonPoolMemory(memory: ComparisonMemory, pool: string) {
  let value = memory.pools.get(pool);
  if (!value) {
    value = { lastCheck: -Infinity, published: null, publicationAt: -Infinity };
    memory.pools.set(pool, value);
  }
  return value;
}
