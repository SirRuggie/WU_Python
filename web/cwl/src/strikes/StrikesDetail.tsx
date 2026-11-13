import type { RefObject } from "react";
import DiscordIdentity from "../DiscordIdentity";
import ReplacementDeparture from "../ReplacementDeparture";
import StrikeActivityDetail from "../StrikeActivityDetail";
import StrikeHistoryRow from "../StrikeHistoryRow";
import StrikeReplacementRow from "../StrikeReplacementRow";
import StrikeStreak, { type StrikeStreakState } from "../StrikeStreak";
import { api } from "../api";
import { memberName } from "../strikeActivityFilters";
import { strikeCountLabel } from "../strikeCountLabel";
import type useDiscordIdentities from "../useDiscordIdentities";
import type { Overview, StrikeAccount } from "./types";

export default function StrikesDetail({
  access,
  busy,
  loading,
  error,
  status,
  overview,
  selectedAccount,
  accountStreak,
  discordProfiles,
  detailHeading,
  page,
  setPage,
  removeId,
  setRemoveId,
  removeReason,
  setRemoveReason,
  setReplacementDirty,
  setReplacementBusy,
  onFindReplacement,
  onMemberAccounts,
  leaveDraft,
  run,
  refreshAfterChange,
}: {
  access: { manage: boolean; remove: boolean };
  busy: boolean;
  loading: boolean;
  error: string;
  status: string;
  overview: Overview;
  selectedAccount: StrikeAccount | null;
  accountStreak: {
    tag: string;
    streak?: StrikeStreakState | null;
  } | null;
  discordProfiles: ReturnType<typeof useDiscordIdentities>;
  detailHeading: RefObject<HTMLHeadingElement | null>;
  page: number;
  setPage: (update: (value: number) => number) => void;
  removeId: string;
  setRemoveId: (id: string) => void;
  removeReason: string;
  setRemoveReason: (reason: string) => void;
  setReplacementDirty: (dirty: boolean) => void;
  setReplacementBusy: (busy: boolean) => void;
  onFindReplacement?: (clan: string, tag: string, weight?: number) => void;
  onMemberAccounts?: (memberId: string) => void;
  leaveDraft: (action: () => void) => void;
  run: (
    action: () => Promise<unknown>,
    success: string,
    after?: () => void | Promise<void>,
  ) => Promise<void>;
  refreshAfterChange: () => Promise<void>;
}) {
  return (
    <>
      {selectedAccount && (
        <div className="strikes-detail-context">
          <h2 ref={detailHeading} tabIndex={-1}>
            {selectedAccount.player_name}
          </h2>
          <div>{selectedAccount.player_tag}</div>
          <DiscordIdentity
            userId={selectedAccount.discord_id}
            linkStatus={selectedAccount.link_status}
            displayName={selectedAccount.discord_name}
            resolvedMember={
              discordProfiles.members[selectedAccount.discord_id || ""] || null
            }
            resolving={discordProfiles.loading}
          />
          {selectedAccount.current_clan_name
            ? `${selectedAccount.clan_is_current === false ? "Last known" : "Current"}: ${selectedAccount.current_clan_name}`
            : "No clan"}{" "}
          · {selectedAccount.active_strikes} active /{" "}
          {strikeCountLabel(selectedAccount.total_strikes, "strike")} in the
          last 90 days
          {((onFindReplacement && selectedAccount.current_clan_tag) ||
            (onMemberAccounts &&
              selectedAccount.discord_id &&
              memberName(selectedAccount))) && (
            <div className="strikes-detail-actions">
              {onFindReplacement && selectedAccount.current_clan_tag && (
                <button
                  onClick={() =>
                    leaveDraft(() =>
                      onFindReplacement(
                        selectedAccount.current_clan_tag!,
                        selectedAccount.player_tag,
                        selectedAccount.weight ?? undefined,
                      ),
                    )
                  }
                >
                  Find a fill for this slot
                </button>
              )}
              {onMemberAccounts &&
                selectedAccount.discord_id &&
                memberName(selectedAccount) && (
                  <button
                    onClick={() =>
                      leaveDraft(() =>
                        onMemberAccounts(selectedAccount.discord_id!),
                      )
                    }
                  >
                    All accounts of @{memberName(selectedAccount)}
                  </button>
                )}
            </div>
          )}
          {selectedAccount.left_clan && (
            <ReplacementDeparture
              clan={selectedAccount.last_clan_name || "family"}
              seenAt={selectedAccount.departed_at}
            />
          )}
          <StrikeActivityDetail account={selectedAccount} />
          <StrikeReplacementRow
            key={selectedAccount.player_tag}
            tag={selectedAccount.player_tag}
            canManage={access.manage}
            onDirty={setReplacementDirty}
            onWorking={setReplacementBusy}
          />
          <StrikeStreak
            loading={loading}
            streak={
              !error && accountStreak?.tag === selectedAccount.player_tag
                ? accountStreak.streak
                : null
            }
          />
        </div>
      )}
      <div className="strikes-list-head">
        <h3>{selectedAccount ? "Strike history" : "War history"}</h3>
        <span>
          {loading ? "Loading…" : strikeCountLabel(overview.total, "record")}
        </span>
      </div>
      {!loading && !error && overview.entries.length === 0 && (
        <div className="card strikes-empty">
          {status === "strikes" ? "No strikes found." : "No records found."}
        </div>
      )}
      <div className="strikes-list">
        {!loading &&
          !error &&
          overview.entries.map((item) => (
            <StrikeHistoryRow
              key={item.id}
              item={item}
              showIdentity={!selectedAccount}
              discordProfile={
                discordProfiles.members[item.discord_id || ""] || null
              }
              identityLoading={discordProfiles.loading}
              canRemove={
                access.remove &&
                item.kind === "strike" &&
                item.status === "active"
              }
              removing={removeId === item.id}
              onRemove={() =>
                leaveDraft(() => {
                  setRemoveId(item.id);
                  setRemoveReason("");
                })
              }
            >
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!removeReason.trim()) return;
                  void run(
                    () =>
                      api(
                        `/strikes/${encodeURIComponent(item.id)}/remove`,
                        "POST",
                        { reason: removeReason.trim() },
                      ),
                    "Strike removed.",
                    async () => {
                      setRemoveId("");
                      setRemoveReason("");
                      await refreshAfterChange();
                    },
                  );
                }}
              >
                <label>
                  Why remove?
                  <input
                    disabled={busy}
                    value={removeReason}
                    onChange={(event) => setRemoveReason(event.target.value)}
                    required
                    maxLength={500}
                  />
                </label>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setRemoveId("");
                    setRemoveReason("");
                  }}
                >
                  Cancel
                </button>
                <button disabled={busy || !removeReason.trim()}>
                  Confirm removal
                </button>
              </form>
            </StrikeHistoryRow>
          ))}
      </div>
      {overview.total > 25 && (
        <div className="strikes-pages">
          <button
            disabled={page === 0 || loading}
            onClick={() =>
              leaveDraft(() => {
                setRemoveId("");
                setRemoveReason("");
                setPage((value) => value - 1);
              })
            }
          >
            Previous
          </button>
          <span>
            {page * 25 + 1}–{Math.min((page + 1) * 25, overview.total)} of{" "}
            {overview.total}
          </span>
          <button
            disabled={(page + 1) * 25 >= overview.total || loading}
            onClick={() =>
              leaveDraft(() => {
                setRemoveId("");
                setRemoveReason("");
                setPage((value) => value + 1);
              })
            }
          >
            Next
          </button>
        </div>
      )}
    </>
  );
}
