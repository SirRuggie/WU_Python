import type { Dispatch, SetStateAction } from "react";
import DiscordIdentity, { discordIdentityName } from "../DiscordIdentity";
import SearchPicker from "../SearchPicker";
import { api } from "../api";
import { toggleLeaveTag } from "../strikeSelections";
import type useDiscordIdentities from "../useDiscordIdentities";
import { dateText } from "./format";
import type { Member, Settings } from "./types";

export default function StrikesLeaveTab({
  busy,
  error,
  settings,
  members,
  memberQuery,
  memberError,
  selectedMember,
  leaveTags,
  setLeaveTags,
  leaveConflict,
  leaveRevision,
  resumeDate,
  setResumeDate,
  endingLeave,
  setEndingLeave,
  discordProfiles,
  onMemberQuery,
  chooseMember,
  run,
  updateSettings,
  onSaved,
}: {
  busy: boolean;
  error: string;
  settings: Settings | null;
  members: Member[];
  memberQuery: string;
  memberError: string;
  selectedMember: string;
  leaveTags: string[];
  setLeaveTags: Dispatch<SetStateAction<string[]>>;
  leaveConflict: boolean;
  leaveRevision: number | null;
  resumeDate: string;
  setResumeDate: (value: string) => void;
  endingLeave: string;
  setEndingLeave: (value: string) => void;
  discordProfiles: ReturnType<typeof useDiscordIdentities>;
  onMemberQuery: (value: string) => void;
  chooseMember: (id: string) => Promise<void>;
  run: (
    action: () => Promise<unknown>,
    success: string,
    after?: () => void | Promise<void>,
  ) => Promise<void>;
  updateSettings: () => Promise<void>;
  onSaved: () => void;
}) {
  const selected = members.find((item) => item.id === selectedMember);
  return (
    <>
      <details className="card strikes-leave-editor">
        <summary>Approve leave</summary>
        <div className="strikes-form">
          <h2>Approve leave</h2>
          <label>
            Find Discord member
            <input
              type="search"
              disabled={busy}
              value={memberQuery}
              onChange={(event) => onMemberQuery(event.target.value)}
              spellCheck={false}
              autoComplete="off"
              placeholder="Name or Discord ID"
            />
          </label>
          {memberError && (
            <p className="notice error" role="alert">
              {memberError} Try searching again.
            </p>
          )}
          {members.length > 0 && (
            <SearchPicker
              label="Member"
              value={selectedMember}
              options={members.map((item) => ({
                value: item.id,
                label:
                  discordIdentityName(item.id, null, item.name) ||
                  "Discord member unavailable",
              }))}
              disabled={busy}
              placeholder="Select member"
              searchPlaceholder="Search members"
              emptyText="No members match."
              onChange={chooseMember}
            />
          )}
          {selected && (
            <DiscordIdentity
              userId={selected.id}
              displayName={selected.name}
              resolvedMember={discordProfiles.members[selected.id] || null}
              resolving={discordProfiles.loading}
            />
          )}
          {selected && (
            <div className="strikes-account-checks">
              <span>Accounts on leave</span>
              {selected.accounts.map((item) => (
                <label key={item.tag}>
                  <input
                    type="checkbox"
                    disabled={busy}
                    checked={leaveTags.includes(item.tag)}
                    onChange={(event) =>
                      setLeaveTags((current) =>
                        toggleLeaveTag(current, item.tag, event.target.checked),
                      )
                    }
                  />
                  {item.name} · {item.tag}
                </label>
              ))}
            </div>
          )}
          <label>
            Resume on (UTC)
            <input
              type="date"
              disabled={busy}
              value={resumeDate}
              min={new Date().toISOString().slice(0, 10)}
              onChange={(event) => setResumeDate(event.target.value)}
            />
          </label>
          <button
            className="primary"
            disabled={
              busy ||
              leaveConflict ||
              leaveRevision === null ||
              !selectedMember ||
              !leaveTags.length ||
              !resumeDate
            }
            onClick={() =>
              void run(
                () =>
                  api("/strikes/settings/leaves", "POST", {
                    discord_id: selectedMember,
                    player_tags: leaveTags,
                    resume_date: resumeDate,
                    revision: leaveRevision,
                  }),
                "Leave saved.",
                async () => {
                  await updateSettings();
                  onSaved();
                },
              )
            }
          >
            Save leave
          </button>
        </div>
      </details>
      {!settings && !error && <p role="status">Loading approved leave…</p>}
      <div className="strikes-list-head">
        <h2>Approved leave</h2>
      </div>
      {settings && settings.leaves.length === 0 && (
        <div className="card strikes-empty">No approved leave.</div>
      )}
      {settings?.leaves.map((item) => (
        <div className="card strikes-leave" key={item.discord_id}>
          <div>
            <DiscordIdentity
              userId={item.discord_id}
              linkStatus={
                "link_status" in item ? (item.link_status as string) : undefined
              }
              displayName={item.display_name}
              resolvedMember={discordProfiles.members[item.discord_id] || null}
              resolving={discordProfiles.loading}
              variant="compact"
            />
            <small>{item.player_tags.join(" · ")}</small>
            <span>Resume on: {dateText(item.resume_date)} UTC</span>
          </div>
          {endingLeave !== item.discord_id ? (
            <button
              disabled={busy}
              onClick={() => setEndingLeave(item.discord_id)}
            >
              End leave
            </button>
          ) : (
            <div className="strikes-inline">
              <span>End leave for {item.display_name} now?</span>
              <button disabled={busy} onClick={() => setEndingLeave("")}>
                Cancel
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void run(
                    () =>
                      api(
                        `/strikes/settings/leaves/${encodeURIComponent(item.discord_id)}`,
                        "DELETE",
                        { revision: item.revision },
                      ),
                    "Leave ended.",
                    async () => {
                      setEndingLeave("");
                      await updateSettings();
                    },
                  )
                }
              >
                Confirm end leave
              </button>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
