import { useEffect, useRef, useState } from "react";
import ModerationDestinationPicker from "./ModerationDestinationPicker";
import ModerationPreviewCard from "./ModerationPreviewCard";
import { Button } from "./rosterUi/primitives";
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
  type SwitchChange,
  type SwitchFeedback,
  type SwitchResult,
} from "./moderationSettingsModel";

type Props = {
  category: CategoryKind;
  label: string;
  icon: string;
  events: { key: ModerationKind; label: string; icon: string; color: string }[];
  draft: SettingsDraft;
  saved: SettingsResponse;
  channels: Destination[];
  busy: boolean;
  inventoryAvailable: boolean;
  dirty: boolean;
  switchFeedback: SwitchFeedback | null;
  onSwitch: (change: SwitchChange) => SwitchResult;
  onCategory: (category: CategoryKind, values: Partial<CategoryConfig>) => void;
  onEvent: (kind: ModerationKind, values: Partial<EventConfig>) => void;
  onResolve: (scope: "category" | "event", key: string, id: string) => void;
  onTest: (kind: ModerationKind) => void;
};

function postingState(
  draft: SettingsDraft,
  kind: ModerationKind,
  channels: Destination[],
  inventoryAvailable: boolean,
) {
  const effective = effectiveDestination(draft, kind);
  const unavailable =
    !!effective.target?.channel_id &&
    (!inventoryAvailable || hasInvalidEventDestination(draft, kind, channels));
  const posting =
    draft.events[kind].enabled &&
    effective.source !== "off" &&
    !!effective.target?.channel_id &&
    !unavailable;
  return { ...effective, unavailable, posting };
}

export function moderationRoutingSummary(
  events: ModerationKind[],
  draft: SettingsDraft,
  channels: Destination[],
  inventoryAvailable: boolean,
) {
  const destinations = new Map<string, string>();
  let notPosting = 0;
  for (const kind of events) {
    const state = postingState(draft, kind, channels, inventoryAvailable);
    if (state.posting && state.target?.channel_id) {
      destinations.set(
        state.target.channel_id,
        destinationName(state.target, channels),
      );
    } else notPosting++;
  }
  if (destinations.size === 0) return "Not posting";
  const place =
    destinations.size === 1
      ? [...destinations.values()][0]
      : `${destinations.size} channels`;
  return `Posts to ${place}${notPosting ? ` · ${notPosting} not posting` : ""}`;
}

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
  switchFeedback,
  onSwitch,
  onCategory,
  onEvent,
  onResolve,
  onTest,
}: Props) {
  const [open, setOpen] = useState(() =>
    events.some(
      (event) =>
        postingState(draft, event.key, channels, inventoryAvailable)
          .unavailable,
    ),
  );
  const [categoryEditing, setCategoryEditing] = useState(false);
  const [openPicker, setOpenPicker] = useState<ModerationKind | null>(null);
  const [openPreview, setOpenPreview] = useState<ModerationKind | null>(null);
  const config = draft.categories[category];
  const active = config.mode !== "off";
  const previousMode = useRef<"main" | "own">(
    config.mode === "own" ? "own" : "main",
  );
  useEffect(() => {
    if (config.mode !== "off") previousMode.current = config.mode;
  }, [config.mode]);
  const selectedCategoryChannel = channels.find(
    (channel) => channel.id === config.channel_id,
  );
  const feedbackFor = (key: string) =>
    switchFeedback?.key === key ? (
      <small
        className={`moderation-switch-feedback roster-ui is-${switchFeedback.state}`}
        role={switchFeedback.state === "error" ? "alert" : "status"}
      >
        {switchFeedback.message}
      </small>
    ) : null;
  const summary = moderationRoutingSummary(
    events.map((event) => event.key),
    draft,
    channels,
    inventoryAvailable,
  );

  return (
    <details
      className="moderation-category-card"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="moderation-category-summary">
        <h3
          id={`moderation-${category}-title`}
          className="moderation-category-head"
        >
          <span className="moderation-category-title">
            <span className="moderation-category-name">
              <span aria-hidden="true">{icon}</span> {label}
            </span>
            <small>{summary}</small>
            {feedbackFor(`category:${category}`)}
          </span>
          <label
            className="moderation-category-switch"
            onClick={(event) => event.stopPropagation()}
          >
            <input
              type="checkbox"
              role="switch"
              aria-label={`${label} logging`}
              checked={active}
              disabled={busy}
              onChange={(event) => {
                const result = onSwitch({
                  scope: "category",
                  key: category,
                  values: {
                    mode: event.target.checked ? previousMode.current : "off",
                  },
                });
                if (result === "draft") {
                  setOpen(true);
                  setCategoryEditing(true);
                }
              }}
            />
            <span className="moderation-category-track" aria-hidden="true" />
            <span>{active ? "On" : "Off"}</span>
          </label>
          <Button
            aria-expanded={categoryEditing}
            disabled={busy}
            onClick={(event) => {
              event.stopPropagation();
              setOpen(true);
              setCategoryEditing((value) => !value);
            }}
          >
            Change
          </Button>
        </h3>
      </summary>
      {categoryEditing && (
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
          {config.mode === "own" &&
            selectedCategoryChannel?.type === "forum" && (
              <small>New notices create posts in this forum.</small>
            )}
        </div>
      )}
      <div className="moderation-event-list">
        {events.map((event) => {
          const value = draft.events[event.key];
          const effective = effectiveDestination(draft, event.key);
          const state = postingState(
            draft,
            event.key,
            channels,
            inventoryAvailable,
          );
          const channel = channels.find(
            (item) => item.id === effective.target?.channel_id,
          );
          const testDisabled =
            busy ||
            dirty ||
            !value.enabled ||
            !effective.target?.channel_id ||
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
          const editing = openPicker === event.key;
          return (
            <div
              className="moderation-event-row"
              data-event={event.key}
              key={event.key}
            >
              <div className="moderation-event-head">
                <label className="moderation-event-pill">
                  <input
                    type="checkbox"
                    role="switch"
                    aria-label={`${event.label} logging`}
                    checked={value.enabled}
                    disabled={busy}
                    onChange={(change) => {
                      const result = onSwitch({
                        scope: "event",
                        key: event.key,
                        values: { enabled: change.target.checked },
                      });
                      if (result === "draft") setOpenPicker(event.key);
                    }}
                  />
                  <span
                    aria-hidden="true"
                    className="moderation-event-pill-track"
                  />
                  <span aria-hidden="true">{event.icon}</span>
                  <span>{event.label}</span>
                </label>
                <Button
                  disabled={busy}
                  aria-expanded={editing}
                  onClick={() => {
                    setOpenPicker(editing ? null : event.key);
                    if (editing) setOpenPreview(null);
                  }}
                >
                  Change
                </Button>
              </div>
              <p
                className={`moderation-event-status roster-ui${state.unavailable ? " is-unavailable" : ""}`}
              >
                {state.unavailable
                  ? "Channel unavailable · not posting"
                  : state.posting
                    ? `Posts to ${destinationName(state.target, channels)}`
                    : "Not posting"}
              </p>
              {feedbackFor(`event:${event.key}`)}
              {editing && (
                <div className="moderation-event-editor">
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
                  <div className="moderation-event-actions">
                    <Button
                      aria-expanded={openPreview === event.key}
                      onClick={() =>
                        setOpenPreview(
                          openPreview === event.key ? null : event.key,
                        )
                      }
                    >
                      Preview
                    </Button>
                    <Button
                      disabled={testDisabled}
                      title={
                        !effective.target?.channel_id
                          ? "Select a channel first"
                          : dirty
                            ? "Save changes first"
                            : undefined
                      }
                      onClick={() => onTest(event.key)}
                    >
                      Send test
                    </Button>
                  </div>
                  {!effective.target?.channel_id && (
                    <small>Select a channel first</small>
                  )}
                  {dirty && <small>Save changes first to send a test.</small>}
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
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
