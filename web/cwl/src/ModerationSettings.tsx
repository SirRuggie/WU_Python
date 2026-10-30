import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import ConfirmDialog from "./ConfirmDialog";
import ModerationCategoryCard from "./ModerationCategoryCard";
import ModerationDestinationPicker from "./ModerationDestinationPicker";
import {
  changedSettings,
  cloneSettings,
  destinationName,
  effectiveDestination,
  eventTypes,
  hasInvalidDestination,
  hasInvalidEventDestination,
  moderationRegistry,
  moderationSettingsError,
  saveModerationSettings,
  type CategoryConfig,
  type CategoryKind,
  type Destination,
  type EventConfig,
  type ModerationKind,
  type RouteTarget,
  type SettingsDraft,
  type SettingsResponse,
} from "./moderationSettingsModel";
import "./ModerationSettings.css";

type DialogState =
  | { type: "test"; event: ModerationKind }
  | { type: "reload" }
  | null;

export default function ModerationSettings({
  onDirty,
}: {
  onDirty?: (dirty: boolean) => void;
}) {
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState<DialogState>(null);
  const request = useRef(0);
  const lastChannels = useRef<Destination[] | null>(null);
  const channels = saved?.channels || [];
  const inventoryAvailable = saved?.channels_available !== false;
  const dirty = !!saved && !!draft && changedSettings(saved, draft);

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
      const fresh =
        result.channels_available !== false && Array.isArray(result.channels);
      if (fresh) lastChannels.current = result.channels || [];
      setSaved({
        ...result,
        channels: fresh
          ? result.channels || []
          : lastChannels.current || result.channels || null,
      });
      setDraft(cloneSettings(result));
    } catch (cause) {
      if (request.current !== id) return;
      const failure = moderationSettingsError(cause, "read");
      if (failure.denied) {
        lastChannels.current = null;
        setSaved(null);
        setDraft(null);
      }
      setError(failure.message);
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

  const clearFeedback = () => {
    setError("");
    setNotice("");
  };
  const updateMain = (value: RouteTarget) => {
    setDraft((current) => (current ? { ...current, main: value } : current));
    clearFeedback();
  };
  const updateCategory = (
    category: CategoryKind,
    values: Partial<CategoryConfig>,
  ) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            categories: {
              ...current.categories,
              [category]: { ...current.categories[category], ...values },
            },
          }
        : current,
    );
    clearFeedback();
  };
  const updateEvent = (kind: ModerationKind, values: Partial<EventConfig>) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            events: {
              ...current.events,
              [kind]: { ...current.events[kind], ...values },
            },
          }
        : current,
    );
    clearFeedback();
  };

  const resolveDestination = async (
    scope: "main" | "category" | "event",
    key: string,
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
      const target = { channel_id: channel.id, forum_tag_id: null };
      if (scope === "main") updateMain(target);
      else if (scope === "category")
        updateCategory(key as CategoryKind, target);
      else updateEvent(key as ModerationKind, target);
      setNotice(`Found #${channel.name}.`);
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

  const invalidDestination =
    !!draft &&
    !!saved &&
    (saved.channels_available === false ||
      hasInvalidDestination(draft, saved.channels));

  const save = async () => {
    if (!saved || !draft || !dirty || busy || invalidDestination) return;
    const id = ++request.current;
    setBusy(true);
    clearFeedback();
    try {
      const result = await saveModerationSettings(saved, draft);
      if (request.current !== id) return;
      setSaved({
        ...result,
        channels: saved.channels,
        channels_available: saved.channels_available,
        warning: saved.warning,
        preview_cards: saved.preview_cards,
        forum_preview_cards: saved.forum_preview_cards,
      });
      setDraft(cloneSettings(result));
      setNotice("Moderation settings saved.");
    } catch (cause) {
      if (request.current !== id) return;
      const failure = moderationSettingsError(cause, "save");
      if (failure.denied) {
        lastChannels.current = null;
        setSaved(null);
        setDraft(null);
      }
      setError(failure.message);
    } finally {
      if (request.current === id) setBusy(false);
    }
  };

  const discard = () => {
    if (!saved || busy) return;
    setDraft(cloneSettings(saved));
    clearFeedback();
  };

  const reloadLatest = () => {
    if (busy || loading) return;
    if (dirty) setDialog({ type: "reload" });
    else void load();
  };

  const startTest = (kind: ModerationKind) => {
    if (!saved || !draft || dirty || busy) return;
    const destination = effectiveDestination(saved, kind);
    if (
      !saved.events[kind].enabled ||
      !destination.target?.channel_id ||
      hasInvalidEventDestination(saved, kind, saved.channels) ||
      !inventoryAvailable
    )
      return;
    setDialog({ type: "test", event: kind });
  };

  const sendTest = async (kind: ModerationKind) => {
    if (!saved || dirty || busy) return;
    const id = ++request.current;
    const revision = saved.revision;
    setDialog(null);
    setBusy(true);
    clearFeedback();
    setNotice("Sending one test log…");
    try {
      await api("/manage/member-events/test", "POST", {
        event_type: kind,
        revision,
      });
      if (request.current !== id) return;
      setNotice("Test log sent. Check the saved destination in Discord.");
    } catch (cause) {
      if (request.current !== id) return;
      const failure = moderationSettingsError(cause, "test");
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

  const testDestination =
    dialog?.type === "test" && saved
      ? effectiveDestination(saved, dialog.event).target
      : null;

  return (
    <section
      className="moderation-settings"
      aria-labelledby="moderation-settings-title"
    >
      <header className="moderation-settings-heading">
        <div>
          <h2 id="moderation-settings-title">Log settings</h2>
          <p>
            Choose where member and moderation notices appear. History remains
            available when posting is off.
          </p>
        </div>
        <button type="button" onClick={reloadLatest} disabled={loading || busy}>
          Reload settings
        </button>
      </header>

      {error && (
        <div className="moderation-settings-error" role="alert">
          <p>{error}</p>
          {error.includes("changed since you loaded") && (
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
          {(saved.warning || !inventoryAvailable) && (
            <p className="moderation-settings-empty" role="status">
              {saved.warning ||
                "Channel inventory is unavailable. Existing destinations are shown when known; reload before saving or testing."}
            </p>
          )}
          {inventoryAvailable && channels.length === 0 && (
            <p className="moderation-settings-empty" role="status">
              No text channels or forums are listed. Check bot permissions or
              look up a forum post ID.
            </p>
          )}

          <div className="moderation-main-route">
            <h3>Main log channel</h3>
            <p>
              Categories and events can use this destination unless you choose
              an override.
            </p>
            <ModerationDestinationPicker
              label="Main log channel"
              value={draft.main}
              channels={channels}
              disabled={busy || loading || !inventoryAvailable}
              onResolve={(id) => void resolveDestination("main", "", id)}
              onChange={updateMain}
            />
          </div>

          <div className="moderation-category-list">
            {moderationRegistry
              .filter(
                (category) =>
                  category.key === "members" || category.key === "moderation",
              )
              .map((category) => (
                <ModerationCategoryCard
                  key={category.key}
                  category={category.key as CategoryKind}
                  label={category.label}
                  icon={category.icon}
                  events={eventTypes.filter(
                    (event) => event.category === category.key,
                  )}
                  draft={draft}
                  saved={saved}
                  channels={channels}
                  busy={busy}
                  inventoryAvailable={inventoryAvailable}
                  dirty={dirty}
                  onCategory={updateCategory}
                  onEvent={updateEvent}
                  onResolve={(scope, key, id) =>
                    void resolveDestination(scope, key, id)
                  }
                  onTest={startTest}
                />
              ))}
          </div>

          {invalidDestination && (
            <p className="moderation-destination-warning" role="status">
              An enabled notice needs an available destination and any required
              forum tag before saving.
            </p>
          )}
          <div className="moderation-settings-save">
            <p>
              <span
                className={
                  dirty ? "moderation-dirty-dot" : "moderation-clean-dot"
                }
                aria-hidden="true"
              />
              {dirty ? "Unsaved changes" : "All changes saved"}
            </p>
            <div>
              <button type="button" onClick={discard} disabled={!dirty || busy}>
                Discard
              </button>
              <button
                className="primary"
                type="button"
                disabled={!dirty || busy || loading || invalidDestination}
                onClick={() => void save()}
              >
                {busy ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        </>
      )}

      {dialog?.type === "reload" && (
        <ConfirmDialog
          heading="Discard changes?"
          text="Discard your unsaved moderation settings and load the latest saved version?"
          confirmLabel="Discard and reload"
          danger
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            setDialog(null);
            void load();
          }}
        />
      )}
      {dialog?.type === "test" && saved && (
        <ConfirmDialog
          heading="Send test log"
          text={`Post a test log to ${destinationName(testDestination, saved.channels)}?`}
          confirmLabel="Send one test"
          disabled={busy || dirty}
          onCancel={() => setDialog(null)}
          onConfirm={() => void sendTest(dialog.event)}
        />
      )}
    </section>
  );
}
