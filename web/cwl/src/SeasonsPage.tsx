import { monthSeasons, seasonMonthLabel } from "./seasonLabels";
import CwlPageHeader from "./CwlPageHeader";
import CwlNextLink from "./CwlNextLink";
import StaffSignupControls from "./StaffSignupControls";
import { useEffect, useRef, useState } from "react";
import LoadError from "./LoadError";
import { Plus } from "lucide-react";
import "./SeasonsPage.css";
import { api, type Season } from "./api";
import { Button, Input, StatusPill } from "./rosterUi/primitives";
import RosterMenu from "./rosterUi/Menu";
import ConfirmDialog from "./ConfirmDialog";
import CwlPoolRoles from "./CwlPoolRoles";
import MemberSeasonSettings from "./MemberSeasonSettings";
import {
  createSeasonConfirmation,
  createdSeasonMessage,
  type SeasonState,
} from "./seasonFlow";
import { useDashboardPermission } from "./DashboardPermissions";

type Props = {
  seasonId: string;
  seasons: Season[];
  memberSeason: SeasonState["member_season"];
  onSeasonChange: (id: string) => void;
  onRefresh: () => Promise<void>;
  onClans?: () => void;
  onBusy: (value: boolean) => void;
  onDirty?: (value: boolean) => void;
};
export default function SeasonsPage({
  seasonId,
  seasons,
  memberSeason,
  onSeasonChange,
  onRefresh,
  onClans,
  onBusy,
  onDirty,
}: Props) {
  const allowed = useDashboardPermission("cwl_settings");
  const season = seasons.find((item) => String(item.id) === seasonId);
  const hiddenOpen =
    !!season?.signup_open && memberSeason.season_id !== season?.id;
  const [label, setLabel] = useState("");
  const [createLabel, setCreateLabel] = useState<string | null>(null);
  const [visibility, setVisibility] = useState<"show" | "hide" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const [roleBusy, setRoleBusy] = useState(false);
  const [signupBusy, setSignupBusy] = useState(false);
  const [roleDirty, setRoleDirty] = useState(false);
  const [signupDirty, setSignupDirty] = useState(false);
  const working = busy || roleBusy || signupBusy;
  useEffect(() => {
    onDirty?.(roleDirty || signupDirty || !!label.trim());
    return () => onDirty?.(false);
  }, [roleDirty, signupDirty, label, onDirty]);
  useEffect(() => {
    onBusy(working);
    return () => onBusy(false);
  }, [working, onBusy]);
  async function save() {
    if (pending.current || !allowed || !createLabel) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setRefreshFailed(false);
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
        setError("Season created. The season list could not refresh.");
        setRefreshFailed(true);
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
    setRefreshFailed(false);
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
        setError((current) =>
          `${current} The season list could not refresh.`.trim(),
        );
        setRefreshFailed(true);
      }
      pending.current = false;
      setBusy(false);
    }
  }
  async function retryRefresh() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setRefreshFailed(false);
    try {
      await onRefresh();
    } catch {
      setError("The season list could not refresh.");
      setRefreshFailed(true);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="roster-ui seasons-page">
      <CwlPageHeader title={<h1>Seasons</h1>}>
        <RosterMenu
          label="Season"
          value={seasonId}
          disabled={working}
          options={monthSeasons(seasons).map((item) => ({
            value: String(item.id),
            label: seasonMonthLabel(item),
          }))}
          onValueChange={onSeasonChange}
        />
      </CwlPageHeader>
      <LoadError
        message={error}
        disabled={working}
        onRetry={refreshFailed ? () => void retryRefresh() : undefined}
      />
      {notice && (
        <p className="notice success" role="status">
          {notice}
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
              tone={hiddenOpen || !season.signup_open ? "warning" : "success"}
            >
              {season.signup_open ? "Signups open" : "Signups closed"}
              {hiddenOpen && " · not visible to members"}
            </StatusPill>
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
      {season && allowed && !onClans && (
        <StaffSignupControls
          season={season}
          onChanged={async () => onRefresh()}
          onBusy={setSignupBusy}
          onDirty={setSignupDirty}
          disabled={busy || roleBusy}
        />
      )}
      <CwlPoolRoles onBusy={setRoleBusy} onDirty={setRoleDirty} />
      <CwlNextLink
        label="Build roster"
        onNext={onClans}
        disabled={working || !seasonId}
      />
    </section>
  );
}
