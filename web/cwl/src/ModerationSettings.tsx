import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import ChannelCombobox from "./ChannelCombobox";
import type { AnnouncementChannel } from "./announcements";
import "./ModerationSettings.css";
import {
  changedEvents,
  cloneEvents,
  eventTypes,
  hasInvalidDestination,
  moderationSettingsError,
  saveModerationSettings,
  type Destination,
  type EventConfig,
  type EventSettings,
  type ModerationKind,
  type SettingsResponse,
} from "./moderationSettingsModel";

export default function ModerationSettings({
  onDirty,
}: {
  onDirty?: (dirty: boolean) => void;
}) {
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<EventSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef(0);
  const lastChannels = useRef<Destination[] | null>(null);
  const channels = useMemo<AnnouncementChannel[]>(
    () =>
      (saved?.channels || [])
        .filter((channel) => channel.can_post)
        .map((channel) => ({
          id: channel.id,
          name: channel.name,
          type:
            channel.type === "forum"
              ? 15
              : channel.type === "forum_post"
                ? 11
                : 0,
        })),
    [saved?.channels],
  );
  const dirty = !!saved && !!draft && changedEvents(saved.events, draft);
  useEffect(() => {
    onDirty?.(dirty);
  }, [dirty, onDirty]);
  useEffect(() => () => onDirty?.(false), [onDirty]);

  const load = useCallback(async () => {
    const id = ++request.current;
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const result = await api<SettingsResponse>(
        "/manage/member-events/settings",
      );
      if (request.current !== id) return;
      const freshInventory =
        result.channels_available !== false && Array.isArray(result.channels);
      if (freshInventory) lastChannels.current = result.channels || [];
      setSaved({
        ...result,
        channels: freshInventory
          ? result.channels || []
          : lastChannels.current || result.channels || null,
      });
      setDraft(cloneEvents(result.events));
    } catch (cause) {
      if (request.current !== id) return;
      const failure = moderationSettingsError(cause, "read");
      if (failure.denied) {
        lastChannels.current = null;
        setSaved(null);
        setDraft(null);
        setError(failure.message);
      } else {
        setError(failure.message);
      }
    } finally {
      if (request.current === id) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      request.current += 1;
    };
  }, [load]);

  const update = (kind: ModerationKind, values: Partial<EventConfig>) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            [kind]: { ...current[kind], ...values },
          }
        : current,
    );
    setError("");
    setNotice("");
  };

  const resolveDestination = async (
    kind: ModerationKind,
    channelId: string,
  ) => {
    if (busy) return;
    const id = ++request.current;
    setBusy(true);
    setError("");
    setNotice("Looking up destination…");
    try {
      const channel = await api<Destination>(
        `/manage/member-events/destinations/${channelId}`,
      );
      if (request.current !== id) return;
      setSaved((current) =>
        current
          ? {
              ...current,
              channels: [
                ...(current.channels || []).filter(
                  (item) => item.id !== channel.id,
                ),
                channel,
              ],
            }
          : current,
      );
      update(kind, { channel_id: channel.id, forum_tag_id: null });
    } catch (cause) {
      if (request.current !== id) return;
      const failure = moderationSettingsError(cause, "read");
      if (failure.denied) {
        lastChannels.current = null;
        setSaved(null);
        setDraft(null);
      }
      setError(failure.message);
      setNotice("");
    } finally {
      if (request.current === id) setBusy(false);
    }
  };

  const selectedChannel = (channelId: string | null) =>
    saved?.channels?.find((channel) => channel.id === channelId);

  const invalidDestination =
    !!saved &&
    (saved.channels_available === false ||
      !draft ||
      hasInvalidDestination(draft, saved.channels));

  const save = async () => {
    if (!saved || !draft || !dirty || busy || invalidDestination) return;
    const id = ++request.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await saveModerationSettings(saved, draft);
      if (request.current !== id) return;
      setSaved({
        ...result,
        channels: saved.channels,
        channels_available: saved.channels_available,
        warning: saved.warning,
      });
      setDraft(cloneEvents(result.events));
      setNotice("Moderation settings saved.");
    } catch (cause) {
      if (request.current !== id) return;
      const failure = moderationSettingsError(cause, "save");
      if (failure.stale) {
        setError(failure.message);
      } else if (failure.denied) {
        lastChannels.current = null;
        setSaved(null);
        setDraft(null);
        setError(failure.message);
      } else {
        setError(failure.message);
      }
    } finally {
      if (request.current === id) setBusy(false);
    }
  };

  const reloadLatest = () => {
    if (
      dirty &&
      !window.confirm(
        "Discard your unsaved moderation settings and load the latest saved version?",
      )
    )
      return;
    void load();
  };

  return (
    <section
      className="moderation-settings"
      aria-labelledby="moderation-settings-title"
    >
      <header className="moderation-settings-heading">
        <div>
          <h2 id="moderation-settings-title">Moderation settings</h2>
          <p>
            Choose notice destinations. History is saved even when Discord
            posting is off. Use a staff-only channel for kick and ban reasons.
          </p>
        </div>
        <button type="button" onClick={reloadLatest} disabled={loading || busy}>
          Reload settings
        </button>
      </header>

      {error && (
        <div className="moderation-settings-error" role="alert">
          <p>{error}</p>
          {error.includes("changed since you loaded them") && (
            <button
              type="button"
              disabled={loading || busy}
              onClick={reloadLatest}
            >
              Discard edits and reload latest
            </button>
          )}
          {!saved && (
            <button
              type="button"
              disabled={loading}
              onClick={() => void load()}
            >
              Try again
            </button>
          )}
        </div>
      )}
      {notice && (
        <p className="moderation-settings-notice" role="status">
          {notice}
        </p>
      )}
      {loading && <p role="status">Loading moderation settings…</p>}
      {!loading && !saved && !error && (
        <p>No moderation settings are available.</p>
      )}
      {saved && draft && (
        <>
          {(saved.warning || saved.channels_available === false) && (
            <p className="moderation-settings-empty" role="status">
              {saved.warning ||
                "Channel permissions are unavailable. Existing destinations are shown when known; reload before saving."}
            </p>
          )}
          {saved.channels_available !== false &&
            (saved.channels || []).length === 0 && (
              <p className="moderation-settings-empty" role="status">
                No text channels or forums are listed. Try looking up a forum
                post ID. Check the bot's server permissions and reload settings.
              </p>
            )}
          <div className="moderation-event-settings">
            {eventTypes.map(({ key, label, explanation }) => {
              const value = draft[key];
              const channel = selectedChannel(value.channel_id);
              const tags =
                channel?.type === "forum" ? channel.available_tags : [];
              const selectableTags = tags.filter(
                (tag) => !tag.moderated || !!channel?.can_manage_threads,
              );
              return (
                <section
                  className="moderation-event-setting"
                  key={key}
                  aria-labelledby={`moderation-${key}-title`}
                >
                  <div className="moderation-event-setting-title">
                    <div>
                      <h3 id={`moderation-${key}-title`}>{label}</h3>
                      <p>{explanation}</p>
                    </div>
                    <label className="moderation-event-toggle">
                      <input
                        type="checkbox"
                        checked={value.enabled}
                        disabled={busy}
                        onChange={(event) =>
                          update(key, { enabled: event.target.checked })
                        }
                      />
                      Post to Discord
                    </label>
                  </div>
                  <ChannelCombobox
                    label={`${label} destination`}
                    channels={channels}
                    value={value.channel_id || ""}
                    disabled={
                      busy || loading || saved.channels_available === false
                    }
                    onResolve={(channelId) =>
                      void resolveDestination(key, channelId)
                    }
                    onChange={(channelId) =>
                      update(key, {
                        channel_id: channelId || null,
                        forum_tag_id:
                          channelId === value.channel_id
                            ? value.forum_tag_id
                            : null,
                      })
                    }
                  />
                  {channel?.type === "forum_post" && (
                    <p className="small">
                      Notices will be replies in this existing forum post.
                    </p>
                  )}
                  {channel?.type === "forum" && (
                    <label className="moderation-forum-tag">
                      Forum tag{" "}
                      {channel.requires_tag ? "(required)" : "(optional)"}
                      <select
                        value={value.forum_tag_id || ""}
                        disabled={busy || selectableTags.length === 0}
                        onChange={(event) =>
                          update(key, {
                            forum_tag_id: event.target.value || null,
                          })
                        }
                      >
                        <option value="">
                          {channel.requires_tag
                            ? "Choose a forum tag"
                            : "No forum tag"}
                        </option>
                        {selectableTags.map((tag) => (
                          <option key={tag.id} value={tag.id}>
                            {tag.name}
                          </option>
                        ))}
                      </select>
                      {tags.length === 0 && channel.requires_tag && (
                        <small>
                          This forum requires a tag, but none are available.
                        </small>
                      )}
                      {tags.some((tag) => tag.moderated) &&
                        !channel.can_manage_threads && (
                          <small>
                            Moderated forum tags are unavailable because the bot
                            cannot manage forum threads.
                          </small>
                        )}
                    </label>
                  )}
                  {value.enabled &&
                    (!channel ||
                      !channel.can_post ||
                      (channel.type === "forum" &&
                        channel.requires_tag &&
                        (!value.forum_tag_id ||
                          !selectableTags.some(
                            (tag) => tag.id === value.forum_tag_id,
                          ))) ||
                      (channel?.type === "forum" &&
                        value.forum_tag_id &&
                        !selectableTags.some(
                          (tag) => tag.id === value.forum_tag_id,
                        ))) && (
                      <p
                        className="moderation-destination-warning"
                        role="status"
                      >
                        {channel && !channel.can_post
                          ? "The bot cannot post in this destination. Choose a channel where it can post."
                          : channel?.type === "forum" && channel.requires_tag
                            ? "Choose an available forum tag before enabling this notice."
                            : "Choose an available destination before enabling this notice."}
                      </p>
                    )}
                  {channel?.type === "forum" &&
                    value.forum_tag_id &&
                    tags.some(
                      (tag) => tag.id === value.forum_tag_id && tag.moderated,
                    ) &&
                    !channel.can_manage_threads && (
                      <p
                        className="moderation-destination-warning"
                        role="status"
                      >
                        This moderated forum tag requires Manage Threads
                        permission.
                      </p>
                    )}
                </section>
              );
            })}
          </div>
          <div className="moderation-settings-save">
            <p>{dirty ? "Unsaved moderation settings" : "All changes saved"}</p>
            <button
              className="primary"
              type="button"
              disabled={!dirty || busy || loading || invalidDestination}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save moderation settings"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
