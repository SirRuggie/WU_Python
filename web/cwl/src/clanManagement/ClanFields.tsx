import ChannelCombobox from "../ChannelCombobox";
import type { AnnouncementChannel } from "../announcements";
import type { Clan } from "./types";
type Choice = { id: string; name: string };
type Props = {
  section: string;
  draft: Clan;
  saved: Clan | null;
  disabled: boolean;
  dirty: boolean;
  data: { types: string[]; town_halls: string[] };
  channels: AnnouncementChannel[];
  roles: Choice[];
  memberQuery: string;
  setMemberQuery: (value: string) => void;
  members: Choice[];
  memberError: string;
  change: (key: string, value: string) => void;
  action: (kind: "emoji" | "thread") => Promise<void>;
  upload: (slot: string, file?: File) => Promise<void>;
};
export default function ClanFields({
  section,
  draft,
  saved,
  disabled,
  dirty,
  data,
  channels,
  roles,
  memberQuery,
  setMemberQuery,
  members,
  memberError,
  change,
  action,
  upload,
}: Props) {
  return (
    <fieldset disabled={disabled}>
      {section === "Details" && (
        <>
          <label>
            Clan name
            <input
              value={draft.name}
              maxLength={120}
              onChange={(e) => change("name", e.target.value)}
            />
          </label>
          <label>
            Clan type
            <select
              value={draft.type}
              onChange={(e) => change("type", e.target.value)}
            >
              <option value="">Not set</option>
              {data.types.map((type) => (
                <option key={type}>{type}</option>
              ))}
            </select>
          </label>
          <label>
            Minimum Town Hall
            <select
              value={draft.th_requirements}
              onChange={(e) => change("th_requirements", e.target.value)}
            >
              <option value="">Not set</option>
              {data.town_halls.map((th) => (
                <option key={th} value={th}>
                  TH {th}
                </option>
              ))}
            </select>
          </label>
          <label>
            Clan profile link
            <input
              type="url"
              value={draft.profile}
              onChange={(e) => change("profile", e.target.value)}
            />
          </label>
        </>
      )}
      {section === "Roles" && (
        <>
          <label>
            Find clan leader
            <input
              type="search"
              placeholder="Member name or Discord ID"
              value={memberQuery}
              onChange={(e) => setMemberQuery(e.target.value)}
            />
          </label>
          {memberError && <p role="alert">{memberError}</p>}
          <label>
            Clan leader
            <select
              value={draft.leader_id}
              onChange={(e) => change("leader_id", e.target.value)}
            >
              <option value="">Not set</option>
              {draft.leader_id &&
                !members.some((m) => m.id === draft.leader_id) && (
                  <option value={draft.leader_id}>
                    Current leader · {draft.leader_id}
                  </option>
                )}
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          {[
            ["leader_role_id", "Leader role"],
            ["role_id", "Clan role"],
          ].map(([key, label]) => (
            <label key={key}>
              {label}
              <select
                value={draft[key]}
                onChange={(e) => change(key, e.target.value)}
              >
                <option value="">Not set</option>
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </>
      )}
      {section === "Channels" && (
        <>
          {[
            ["chat_channel_id", "Chat channel"],
            ["announcement_id", "Announcement channel"],
            ["rules_channel_id", "Rules channel"],
            ["leadership_channel_id", "Leadership channel"],
            ["thread_id", "Clan thread"],
          ].map(([key, label]) => (
            <div key={key}>
              <ChannelCombobox
                label={label}
                channels={channels.filter((c) =>
                  key === "thread_id"
                    ? [10, 11, 12].includes(c.type)
                    : [0, 5].includes(c.type),
                )}
                value={draft[key]}
                disabled={disabled}
                onChange={(value) => change(key, value)}
              />
            </div>
          ))}
          <button
            type="button"
            disabled={dirty || disabled}
            onClick={() => void action("thread")}
          >
            Find or create clan thread
          </button>
          {dirty && <small>Save changes before creating a thread.</small>}
        </>
      )}
      {section === "Artwork" && (
        <>
          {["logo", "banner"].map((slot) => (
            <div className="clan-artwork" key={slot}>
              <label>
                {slot === "logo" ? "Clan logo" : "Clan banner"}
                <input
                  type="url"
                  placeholder="Paste an image link"
                  value={draft[slot]}
                  onChange={(e) => change(slot, e.target.value)}
                />
              </label>
              {draft[slot] && (
                <img src={draft[slot]} alt={slot} loading="lazy" />
              )}
              <div className="clan-tabs">
                <button
                  type="button"
                  disabled={!draft[slot]}
                  onClick={() => void upload(slot)}
                >
                  Upload from link
                </button>
                <label>
                  Upload {slot}
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/gif,image/webp"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      if (file) void upload(slot, file);
                    }}
                  />
                </label>
              </div>
            </div>
          ))}
          <label>
            Discord clan emoji
            <input
              placeholder="<:name:emoji_id>"
              value={draft.emoji}
              onChange={(e) => change("emoji", e.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={dirty || !saved?.logo || disabled}
            onClick={() => void action("emoji")}
          >
            Create emoji from saved logo
          </button>
          {dirty && <small>Save artwork before creating the emoji.</small>}
        </>
      )}
    </fieldset>
  );
}
