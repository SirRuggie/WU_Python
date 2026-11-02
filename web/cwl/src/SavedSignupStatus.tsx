import { useEffect, useState } from "react";
import { api, ApiError, type Account, type Season, type Signup } from "./api";
import type { MyAssignments } from "./publication";
import MemberSignupStatus from "./MemberSignupStatus";

export default function SavedSignupStatus({
  signups,
  accounts,
  season,
  onRemaining,
  onAssignments,
}: {
  signups: Signup[];
  accounts: Account[] | null;
  season: Season;
  onRemaining: () => void;
  onAssignments: () => void;
}) {
  const requestKey = `${season.id}:${JSON.stringify(signups)}`;
  const [loadedKey, setLoadedKey] = useState("");
  const [publication, setPublication] = useState<MyAssignments | null>(null);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let active = true;
    setPublication(null);
    setLoading(true);
    setDenied(false);
    setUnavailable(false);
    void api<MyAssignments>(
      `/seasons/${encodeURIComponent(season.id)}/my-assignments`,
    )
      .then((result) => {
        if (active) setPublication(result);
      })
      .catch((cause) => {
        if (active) {
          setUnavailable(true);
          setDenied(
            cause instanceof ApiError && [401, 403].includes(cause.status),
          );
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
          setLoadedKey(requestKey);
        }
      });
    return () => {
      active = false;
    };
  }, [season.id, requestKey]);
  if (loading || loadedKey !== requestKey)
    return <p role="status">Checking clan assignments…</p>;
  if (denied)
    return (
      <p role="alert">Your account access changed. Refresh or sign in again.</p>
    );
  const rows = signups.map((signup) => ({
    ...signup,
    assigned_clan_tag: publication?.accounts?.find(
      (row) => row.tag === signup.tag,
    )?.assigned_clan_tag,
  }));
  return (
    <MemberSignupStatus
      savedView
      publicationUnavailable={unavailable}
      signups={rows}
      accounts={accounts}
      season={season}
      published={!!publication?.published}
      onRemaining={onRemaining}
      onAssignments={onAssignments}
    />
  );
}
