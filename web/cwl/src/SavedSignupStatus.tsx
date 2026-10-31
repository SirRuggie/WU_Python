import { useEffect, useState } from "react";
import { api, type Account, type Season, type Signup } from "./api";
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
  const [publication, setPublication] = useState<MyAssignments | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let active = true;
    setPublication(null);
    setUnavailable(false);
    void api<MyAssignments>(
      `/seasons/${encodeURIComponent(season.id)}/my-assignments`,
    )
      .then((result) => {
        if (active) setPublication(result);
      })
      .catch(() => {
        if (active) setUnavailable(true);
      });
    return () => {
      active = false;
    };
  }, [season.id, signups]);
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
