import { useEffect, useRef, useState, type CSSProperties } from "react";
import ModerationDestinationPicker from "./ModerationDestinationPicker";
import ModerationPreviewCard from "./ModerationPreviewCard";
import {
  destinationName,
  effectiveDestination,
  hasInvalidEventDestination,
  type CategoryConfig,
  type CategoryKind,
  type Destination,
  type EventConfig,
  type ModerationKind,
  type SettingsDraft,
  type SettingsResponse,
} from "./moderationSettingsModel";

type Props = {
  category: CategoryKind;
  label: string;
  icon: string;
  events: {
    key: ModerationKind;
    label: string;
    icon: string;
    color: string;
  }[];
  draft: SettingsDraft;
  saved: SettingsResponse;
  channels: Destination[];
  busy: boolean;
  inventoryAvailable: boolean;
  dirty: boolean;
  onCategory: (category: CategoryKind, values: Partial<CategoryConfig>) => void;
  onEvent: (kind: ModerationKind, values: Partial<EventConfig>) => void;
  onResolve: (scope: "category" | "event", key: string, id: string) => void;
  onTest: (kind: ModerationKind) => void;
};

export default function ModerationCategoryCard({
  category,
  label,
  icon,
  events,
  draft,
  saved,
  channels,
  busy,
  inventoryAvailable,
  dirty,
  onCategory,
  onEvent,
  onResolve,
  onTest,
}: Props) {
  const [openPicker, setOpenPicker] = useState<ModerationKind | null>(null);
  const [openPreview, setOpenPreview] = useState<ModerationKind | null>(null);
  const config = draft.categories[category];
  const active = config.mode !== "off";
  const hasChannel = events.some(
    (event) => effectiveDestination(draft, event.key).target?.channel_id,
  );
  const previousMode = useRef<"main" | "own">(
    config.mode === "own" ? "own" : "main",
  );
  useEffect(() => {
    if (config.mode !== "off") previousMode.current = config.mode;
  }, [config.mode]);
  const selectedCategoryChannel = channels.find(
    (channel) => channel.id === config.channel_id,
  );

  return (
    <section
      className="moderation-category-card"
      aria-labelledby={`moderation-${category}-title`}
    >
      <header className="moderation-category-head">
        <h3 id={`moderation-${category}-title`}>
          <span aria-hidden="true">{icon}</span> {label}
        </h3>
        <label className="moderation-category-switch">
          <input
            type="checkbox"
            role="switch"
            aria-label={`${label} logging`}
            checked={active}
            disabled={busy}
            onChange={(event) =>
              onCategory(category, {
                mode: event.target.checked ? previousMode.current : "off",
              })
            }
          />
          <span className="moderation-category-track" aria-hidden="true" />
          <span>
            {!active
              ? "Off"
              : hasChannel
                ? "On"
                : "Not posting — no channel set"}
          </span>
        </label>
      </header>
      <div className="moderation-category-routing">
        <label>
          {label} destination
          <select
            value={config.mode}
            disabled={busy}
            onChange={(event) =>
              onCategory(category, {
                mode: event.target.value as CategoryConfig["mode"],
              })
            }
          >
            <option value="main">Use main</option>
            <option value="own">Own channel</option>
            <option value="off">Off</option>
          </select>
        </label>
        {config.mode === "own" && (
          <ModerationDestinationPicker
            label={`${label} channel`}
            value={config}
            channels={channels}
            disabled={busy || !inventoryAvailable}
            onResolve={(id) => onResolve("category", category, id)}
            onChange={(value) => onCategory(category, value)}
          />
        )}
        {config.mode === "own" && selectedCategoryChannel?.type === "forum" && (
          <small>New notices create posts in this forum.</small>
        )}
      </div>
      <div className="moderation-event-list">
        {events.map((event) => {
          const value = draft.events[event.key];
          const effective = effectiveDestination(draft, event.key);
          const channel = channels.find(
            (item) => item.id === effective.target?.channel_id,
          );
          const sourceName =
            effective.source === "event"
              ? "its own"
              : effective.source === "category"
                ? `${label}'s`
                : "main's";
          const hint =
            effective.source === "off"
              ? `${label} is off · no log sent`
              : !effective.target?.channel_id
                ? "Not posting — no channel set"
                : `Uses ${sourceName} channel · ${destinationName(effective.target, channels)}`;
          const testDisabled =
            busy ||
            dirty ||
            !value.enabled ||
            effective.source === "off" ||
            hasInvalidEventDestination(saved, event.key, channels) ||
            !inventoryAvailable;
          const selectedOverride = channels.find(
            (item) => item.id === value.channel_id,
          );
          const forumPreview = channel?.type === "forum";
          const preview = forumPreview
            ? saved.forum_preview_cards?.[event.key]
            : saved.preview_cards?.[event.key];

          return (
            <div
              className="moderation-event-row"
              key={event.key}
              style={{ "--moderation-accent": event.color } as CSSProperties}
            >
              <label className="moderation-event-pill">
                <input
                  type="checkbox"
                  role="switch"
                  aria-label={`${event.label} logging`}
                  checked={value.enabled}
                  disabled={busy}
                  onChange={(change) =>
                    onEvent(event.key, { enabled: change.target.checked })
                  }
                />
                <span
                  aria-hidden="true"
                  className="moderation-event-pill-track"
                />
                <span aria-hidden="true">{event.icon}</span>
                <span>{event.label}</span>
              </label>
              <div className="moderation-event-tools">
                <small>{hint}</small>
                <div className="moderation-event-actions">
                  <button
                    type="button"
                    disabled={busy}
                    aria-expanded={openPicker === event.key}
                    onClick={() =>
                      setOpenPicker(openPicker === event.key ? null : event.key)
                    }
                  >
                    Change
                  </button>
                  <button
                    type="button"
                    aria-expanded={openPreview === event.key}
                    onClick={() =>
                      setOpenPreview(
                        openPreview === event.key ? null : event.key,
                      )
                    }
                  >
                    Preview
                  </button>
                  <button
                    type="button"
                    disabled={testDisabled}
                    title={dirty ? "Save changes first" : undefined}
                    onClick={() => onTest(event.key)}
                  >
                    Send test
                  </button>
                </div>
                {dirty && <small>Save changes first to send a test.</small>}
              </div>
              {openPicker === event.key && (
                <div className="moderation-event-override">
                  <div
                    className="moderation-override-options"
                    role="group"
                    aria-label={`${event.label} destination mode`}
                  >
                    <button
                      type="button"
                      aria-pressed={!value.channel_id}
                      disabled={busy}
                      onClick={() =>
                        onEvent(event.key, {
                          channel_id: null,
                          forum_tag_id: null,
                        })
                      }
                    >
                      Use category
                    </button>
                    <button
                      type="button"
                      aria-pressed={!!value.channel_id}
                      disabled={busy}
                      onClick={() => {
                        if (!value.channel_id) {
                          const inherited = effectiveDestination(
                            draft,
                            event.key,
                          ).target;
                          if (inherited?.channel_id)
                            onEvent(event.key, inherited);
                        }
                      }}
                    >
                      Own channel
                    </button>
                  </div>
                  <ModerationDestinationPicker
                    label={`${event.label} channel override`}
                    value={value}
                    channels={channels}
                    disabled={busy || !inventoryAvailable}
                    onResolve={(id) => onResolve("event", event.key, id)}
                    onChange={(target) => onEvent(event.key, target)}
                  />
                  {selectedOverride?.type === "forum" && (
                    <small>New notices create posts in this forum.</small>
                  )}
                </div>
              )}
              {openPreview === event.key && (
                <div className="moderation-event-preview">
                  <h4>{event.label} preview</h4>
                  <ModerationPreviewCard
                    payload={preview}
                    names={saved.preview_names}
                    forum={forumPreview}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
