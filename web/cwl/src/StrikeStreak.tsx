export type StrikeStreakState = { count: number; last_war_key?: string | null };

export default function StrikeStreak({
  streak,
  loading = false,
}: {
  streak?: StrikeStreakState | null;
  loading?: boolean;
}) {
  if (loading) return <p className="strikes-streak">Streak: Loading…</p>;
  if (
    !streak ||
    !Number.isInteger(streak.count) ||
    streak.count < 0 ||
    streak.count > 5
  ) {
    return <p className="strikes-streak">Streak: Unavailable</p>;
  }
  const count = streak.count;
  const remaining = count >= 4 ? 6 - count : 2 - (count % 2);
  return (
    <p className="strikes-streak">
      Streak: {count} {count === 1 ? "war" : "wars"} played · {remaining} more
      to {count >= 4 ? "clear all strikes" : "lose a strike"}
    </p>
  );
}
