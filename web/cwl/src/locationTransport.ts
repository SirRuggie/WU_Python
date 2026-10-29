import { fetchReadWithRetry } from "./readRetry";
import { handleAuthorizationFailure } from "./api";
import type { ComparisonLocation } from "./comparisonLocation";

export type PublishedComparisonAccount = {
  tag: string;
  assigned_clan_tag: string | null;
  assigned_clan_name: string | null;
};
export type ArrivalResponse = {
  source: "draft" | "published";
  updating: boolean;
  accounts: (ComparisonLocation & PublishedComparisonAccount)[];
};

// Read-only transport: an offline Compare read must not POST diagnostic reports.
export async function readArrival(
  season: string,
  published: boolean,
  force: boolean,
  signal: AbortSignal,
): Promise<ArrivalResponse> {
  const response = await fetchReadWithRetry(
    `/api/cwl/seasons/${encodeURIComponent(season)}/arrival-check?source=${published ? "published" : "draft"}&background=1${force ? "&refresh=1" : ""}`,
    { credentials: "same-origin", signal },
  );
  if (!response.ok) {
    handleAuthorizationFailure(response.status);
    throw new Error("Location check failed");
  }
  return response.json();
}
