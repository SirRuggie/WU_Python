import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import DiscordIdentity, { discordIdentityName } from "./DiscordIdentity";
import "./MemberActivityHistory.css";
import MemberEventRow, { type MemberEvent } from "./MemberEventRow";

type Member = {
  user_id: string;
  display_name?: string | null;
  username?: string | null;
  avatar_url?: string | null;
};
type Response = {
  member: Member;
  events: MemberEvent[];
  next_before: string | null;
};

export default function MemberTimeline({
  userId,
  onBack,
}: {
  userId: string;
  onBack: () => void;
}) {
  const [member, setMember] = useState<Member | null>(null);
  const [rows, setRows] = useState<MemberEvent[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(0);

  const load = useCallback(
    async (before: string | null) => {
      const id = ++request.current;
      setLoading(true);
      setError("");
      const params = new URLSearchParams({ limit: "50" });
      if (before) params.set("before", before);
      try {
        const result = await api<Response>(
          `/manage/member-events/members/${encodeURIComponent(userId)}?${params}`,
        );
        if (request.current !== id) return;
        setMissing(false);
        setMember(result.member);
        setRows((current) =>
          before ? [...current, ...result.events] : result.events,
        );
        setNextBefore(result.next_before || null);
      } catch (cause) {
        if (request.current !== id) return;
        if (cause instanceof ApiError && cause.status === 404) {
          setMissing(true);
          setMember(null);
          setRows([]);
          setNextBefore(null);
        } else if (
          cause instanceof ApiError &&
          (cause.status === 401 || cause.status === 403)
        ) {
          setMember(null);
          setRows([]);
          setNextBefore(null);
          setError(
            "Your staff access has changed. Sign in again or ask an administrator to restore access.",
          );
        } else {
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not load member history. Try again.",
          );
        }
      } finally {
        if (request.current === id) setLoading(false);
      }
    },
    [userId],
  );

  useEffect(() => {
    setMember(null);
    setRows([]);
    setNextBefore(null);
    setMissing(false);
    void load(null);
    return () => {
      request.current += 1;
    };
  }, [load]);

  const name = member
    ? discordIdentityName(member.user_id, {
        id: member.user_id,
        display_name: member.display_name || undefined,
        username: member.username || undefined,
      })
    : "";
  const username = member
    ? discordIdentityName(member.user_id, {
        id: member.user_id,
        username: member.username || undefined,
      })
    : "";

  return (
    <section
      className="member-activity member-timeline"
      aria-labelledby="member-timeline-title"
    >
      <header className="member-activity-heading">
        <div>
          <h2 id="member-timeline-title">Member history</h2>
        </div>
        <button type="button" onClick={onBack}>
          Activity history
        </button>
      </header>

      {member && (
        <div className="member-timeline-member">
          <DiscordIdentity
            userId={member.user_id}
            resolvedMember={{
              id: member.user_id,
              display_name: name || "",
              username: username || "",
              avatar_url: member.avatar_url,
            }}
            contact={false}
          />
        </div>
      )}

      {error && (
        <div className="member-activity-error" role="alert">
          {error}
          <button
            type="button"
            disabled={loading}
            onClick={() => void load(null)}
          >
            Try again
          </button>
        </div>
      )}
      {loading && (
        <p role="status" className="member-activity-status">
          {rows.length ? "Updating history…" : "Loading member history…"}
        </p>
      )}
      {(missing || (!error && rows.length === 0)) && !loading && (
        <div className="member-activity-empty">
          <p>No history for this member.</p>
        </div>
      )}
      {rows.length > 0 && (
        <>
          <ul className="member-activity-list" aria-label="Member history">
            {rows.map((item) => (
              <MemberEventRow key={item.id} item={item} />
            ))}
          </ul>
          {nextBefore && (
            <div className="member-activity-more">
              <button
                type="button"
                disabled={loading}
                onClick={() => void load(nextBefore)}
              >
                Load more
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
