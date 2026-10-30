import { useEffect, useState } from "react";
import { api } from "./api";
import HistoryTime from "./clanManagement/HistoryTime";

type Event = {
  id: string;
  action: string;
  at: string | null;
  actor: string;
  source: string;
  clan: Record<string, string>;
  can_restore: boolean;
  present: boolean;
  display?: Record<string, string>;
  reminder_snapshot?: { field: string; value: string }[];
  changes?: { field: string; before: string; after: string }[];
};
type History = { events: Event[]; more: boolean };
const fields: Record<string, string> = {
  type: "Clan type",
  th_requirements: "Minimum Town Hall",
  leader_id: "Leader",
  leader_role_id: "Leader role",
  role_id: "Clan role",
  chat_channel_id: "Chat channel",
  announcement_id: "Announcement channel",
  rules_channel_id: "Rules channel",
  leadership_channel_id: "Leadership channel",
  thread_id: "Thread",
  profile: "Profile link",
  logo: "Logo link",
  banner: "Banner link",
  emoji: "Clan emoji",
};
function day(at: string | null) {
  return at && Number.isFinite(Date.parse(at))
    ? new Date(at).toLocaleDateString(undefined, { dateStyle: "long" })
    : "Date unavailable";
}
export default function ClanHistory({
  onRestored,
}: {
  onRestored: () => void;
}) {
  const [query, setQuery] = useState(""),
    [kind, setKind] = useState("all"),
    [page, setPage] = useState(0),
    [data, setData] = useState<History>({ events: [], more: false }),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [review, setReview] = useState(""),
    [confirmTag, setConfirmTag] = useState(""),
    [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setReview("");
    setConfirmTag("");
    const timer = setTimeout(() => {
      api<History>(
        `/manage/clan-history?page=${page}&kind=${kind}&q=${encodeURIComponent(query)}`,
      )
        .then((result) => {
          if (active) setData(result);
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query, kind, page, refresh]);
  async function restore(event: Event) {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ message: string }>(
        `/manage/clan-history/${encodeURIComponent(event.id)}/restore`,
        "POST",
        { confirm_tag: confirmTag },
      );
      setNotice(result.message);
      setReview("");
      setRefresh((v) => v + 1);
      onRestored();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not restore clan.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Clan settings history" className="clan-history">
      <div className="page-head">
        <div>
          <h2>History</h2>
          <p>Review earlier clan settings or restore a removed clan.</p>
        </div>
        <button
          disabled={busy || loading}
          onClick={() => setRefresh((v) => v + 1)}
        >
          Refresh history
        </button>
      </div>
      <div className="clan-history-filters">
        <label>
          Find a clan
          <input
            type="search"
            placeholder="Clan name or tag"
            disabled={busy}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <label>
          Show
          <select
            disabled={busy}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setPage(0);
            }}
          >
            <option value="all">All changes</option>
            <option value="settings">Clan settings</option>
            <option value="reminders">War reminders</option>
            <option value="added">Added clans</option>
            <option value="restored">Restored clans</option>
            <option value="removed">Removed clans</option>
          </select>
        </label>
      </div>
      <p className="small">
        Confirmed changes show what changed; older entries show saved settings.
        For reminder sends, open War reminders and expand Delivery history.
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {loading ? (
        <p role="status">Loading saved settings…</p>
      ) : data.events.length === 0 ? (
        <div className="card">
          <h3>No saved settings found</h3>
          <p>
            New clan changes will appear here. Older changes may not have a
            saved copy.
          </p>
        </div>
      ) : (
        <div className="clan-history-list">
          {data.events.map((event, index) => (
            <div key={event.id}>
              {(index === 0 ||
                day(event.at) !== day(data.events[index - 1].at)) && (
                <h3>{day(event.at)}</h3>
              )}
              <article className="card">
                <div className="clan-history-heading">
                  <div>
                    <h3>{event.clan.name}</h3>
                    <span className="small">{event.clan.tag}</span>
                  </div>
                  <span className="pill">{event.source}</span>
                </div>
                <p>
                  <strong>{event.action}</strong>
                </p>
                <div className="small">
                  By {event.actor} · <HistoryTime at={event.at} />
                </div>
                {event.changes?.map((change) => (
                  <p key={change.field}>
                    {change.field}: {change.before || "Not set"} →{" "}
                    {change.after || "Not set"}
                  </p>
                ))}
                <details>
                  <summary>
                    {event.changes?.length
                      ? "View settings before this change"
                      : "Settings before this change · View"}
                  </summary>
                  <dl className="clan-history-values">
                    {Object.entries(fields)
                      .filter(([key]) => event.clan[key])
                      .map(([key, label]) => (
                        <div key={key}>
                          <dt>{label}</dt>
                          <dd>
                            {event.display?.[key] ||
                              (key.endsWith("_id")
                                ? "Name not recorded"
                                : event.clan[key])}
                          </dd>
                        </div>
                      ))}
                    {event.reminder_snapshot?.map((setting) => (
                      <div key={`reminder-${setting.field}`}>
                        <dt>{setting.field}</dt>
                        <dd>{setting.value}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
                {event.can_restore ? (
                  <>
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() => {
                        setReview(event.id);
                        setConfirmTag("");
                      }}
                    >
                      Review restore
                    </button>
                    {review === event.id && (
                      <form
                        className="clan-restore"
                        onSubmit={(e) => {
                          e.preventDefault();
                          void restore(event);
                        }}
                      >
                        <h4>Restore {event.clan.name}?</h4>
                        <p>
                          Restores this clan’s saved settings. Check that its
                          roles, channels and image links still exist.
                        </p>
                        <p className="small">
                          CWL rosters and Discord members are not changed.
                        </p>
                        <label>
                          Type {event.clan.tag} to confirm
                          <input
                            autoComplete="off"
                            value={confirmTag}
                            disabled={busy}
                            onChange={(e) => setConfirmTag(e.target.value)}
                          />
                        </label>
                        <div className="clan-tabs">
                          <button
                            className="primary"
                            disabled={busy || confirmTag !== event.clan.tag}
                          >
                            {busy ? "Restoring…" : "Restore clan"}
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setReview("")}
                          >
                            Cancel
                          </button>
                        </div>
                      </form>
                    )}
                  </>
                ) : event.present ? (
                  <p className="small">
                    Clan is active · current settings are kept.
                  </p>
                ) : (
                  <p className="small">
                    View only · use the latest removal snapshot to restore.
                  </p>
                )}
              </article>
            </div>
          ))}
        </div>
      )}
      <nav className="clan-tabs" aria-label="Settings history pages">
        <button
          disabled={busy || loading || page === 0}
          onClick={() => setPage((v) => v - 1)}
        >
          Previous
        </button>
        <span>Page {page + 1}</span>
        <button
          disabled={busy || loading || !data.more}
          onClick={() => setPage((v) => v + 1)}
        >
          Next
        </button>
      </nav>
    </section>
  );
}
