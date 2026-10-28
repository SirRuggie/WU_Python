import { useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { api, type Season } from "./api";
import { Button, Input, StatusPill } from "./rosterUi/primitives";
import RosterMenu from "./rosterUi/Menu";
import ConfirmDialog from "./ConfirmDialog";
import MemberSeasonSettings from "./MemberSeasonSettings";
import useSignupAction from "./useSignupAction";
import {
  createSeasonConfirmation,
  createdSeasonMessage,
  type SeasonState,
} from "./seasonFlow";
import { useDashboardPermission } from "./DashboardPermissions";

type Props = {
  userId: string;
  seasonId: string;
  seasons: Season[];
  memberSeason: SeasonState["member_season"];
  onSeasonChange: (id: string) => void;
  onRefresh: () => Promise<void>;
  onClans: () => void;
  onBusy: (value: boolean) => void;
};
export default function SeasonsPage({
  userId,
  seasonId,
  seasons,
  memberSeason,
  onSeasonChange,
  onRefresh,
  onClans,
  onBusy,
}: Props) {
  const allowed = useDashboardPermission("cwl_settings");
  const season = seasons.find((item) => String(item.id) === seasonId);
  const signup = useSignupAction(season, onRefresh);
  const [label, setLabel] = useState("");
  const [createLabel, setCreateLabel] = useState<string | null>(null);
  const [visibility, setVisibility] = useState<"show" | "hide" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const key = `wu-hosting-clans-moved:${userId}`;
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(key) === "1";
    } catch {
      return false;
    }
  });
  const working = busy || signup.busy;
  useEffect(() => {
    onBusy(working);
    return () => onBusy(false);
  }, [working, onBusy]);
  async function save() {
    if (pending.current || !allowed || !createLabel) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const chosen = createLabel;
    setCreateLabel(null);
    try {
      const result = await api<Season & { copied_clan_count: number }>(
        "/seasons",
        "POST",
        { label: chosen, signup_open: false },
      );
      setNotice(createdSeasonMessage(result.label, result.copied_clan_count));
      setLabel("");
      try {
        await onRefresh();
        onSeasonChange(String(result.id));
      } catch {
        setError("Season created. Refresh to see the latest season list.");
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not create season.",
      );
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  async function setVisible() {
    if (!visibility || pending.current || !allowed) return;
    const target = visibility === "show" ? season?.id : null;
    if (target === undefined) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setVisibility(null);
    try {
      await api("/member-season", "PUT", {
        season_id: target,
        revision: memberSeason.revision,
      });
      setNotice(
        target ? "Member season updated." : "CWL season hidden from members.",
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not change visibility.",
      );
    } finally {
      try {
        await onRefresh();
      } catch {
        setError((current) => `${current} Refresh the season list.`);
      }
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="roster-ui seasons-page">
      <div className="page-head">
        <h1>Seasons</h1>
        <RosterMenu
          label="Season"
          value={seasonId}
          disabled={working}
          options={seasons.map((item) => ({
            value: String(item.id),
            label: item.label,
          }))}
          onValueChange={onSeasonChange}
        />
      </div>
      {!dismissed && (
        <div className="notice">
          <button onClick={onClans}>
            Hosting clans moved to Build roster → Clan settings ›
          </button>
          <button
            aria-label="Dismiss hosting clans note"
            onClick={() => {
              setDismissed(true);
              try {
                localStorage.setItem(key, "1");
              } catch {
                /* Optional preference. */
              }
            }}
          >
            ×
          </button>
        </div>
      )}
      {(error || signup.error) && (
        <p className="notice error" role="alert">
          {error || signup.error}
        </p>
      )}
      {(notice || signup.notice) && (
        <p className="notice success" role="status">
          {notice || signup.notice}
        </p>
      )}
      <div className="card">
        <MemberSeasonSettings
          selected={season}
          active={seasons.find((item) => item.id === memberSeason.season_id)}
          busy={working || !allowed}
          onShow={() => setVisibility("show")}
          onHide={() => setVisibility("hide")}
        />
        {season && (
          <div className="staff-row">
            <StatusPill
              tone={
                signup.hiddenOpen || !season.signup_open ? "warning" : "success"
              }
            >
              {season.signup_open ? "Signups open" : "Signups closed"}
              {signup.hiddenOpen && " · not visible to members"}
            </StatusPill>
            {allowed && season.status !== "archived" && (
              <>
                {signup.hiddenOpen && (
                  <Button
                    disabled={working}
                    onClick={() => void signup.begin("fix")}
                  >
                    Fix ›
                  </Button>
                )}
                <Button
                  disabled={working}
                  onClick={() =>
                    void signup.begin(season.signup_open ? "close" : "open")
                  }
                >
                  {season.signup_open ? "Close signups" : "Open signups"}
                </Button>
              </>
            )}
          </div>
        )}
      </div>
      {allowed && (
        <form
          className="card"
          onSubmit={(event) => {
            event.preventDefault();
            if (!working && label.trim().length >= 3)
              setCreateLabel(label.trim());
          }}
        >
          <h2>Create season</h2>
          <Input
            label="New season label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="November 2026"
            maxLength={80}
          />
          <Button
            icon={Plus}
            type="submit"
            disabled={working || label.trim().length < 3}
          >
            Create season
          </Button>
        </form>
      )}
      {createLabel && (
        <ConfirmDialog
          heading="Create season"
          text={createSeasonConfirmation(createLabel, seasons.length === 0)}
          confirmLabel="Create season"
          onCancel={() => setCreateLabel(null)}
          onConfirm={() => void save()}
          disabled={working || !allowed}
        />
      )}
      {visibility && (
        <ConfirmDialog
          heading="Season visibility"
          text={
            visibility === "show"
              ? `Show ${season?.label} to members?`
              : "Hide the current season from members? Signups and assignments stay saved."
          }
          confirmLabel={
            visibility === "show" ? "Show to members" : "Hide season"
          }
          onCancel={() => setVisibility(null)}
          onConfirm={() => void setVisible()}
          disabled={working || !allowed}
        />
      )}
      {signup.dialog}
    </section>
  );
}
