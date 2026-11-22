import {
  clearStartOperation,
  readStartOperation,
  saveStartOperation,
  type StartOperation,
} from "./seasonStartRecovery";
import {
  monthSeasons,
  nextMonthCycle,
  seasonMonth,
  seasonMonthLabel,
} from "./seasonLabels";
import CwlPageHeader from "./CwlPageHeader";
import CwlNextLink from "./CwlNextLink";
import useSignupAction from "./useSignupAction";
import {
  lifecycleSeason,
  lifecycleStepStates,
  loadLifecycleReadiness,
  type LifecycleReadiness,
} from "./seasonLifecycle";
import { signupGateWarning, type CampaignState } from "./reminderCampaign";
import { useEffect, useRef, useState } from "react";
import LoadError from "./LoadError";
import { Plus } from "lucide-react";
import "./SeasonsPage.css";
import { api, type Season } from "./api";
import { Button, Input } from "./rosterUi/primitives";
import ConfirmDialog from "./ConfirmDialog";
import CwlPoolRoles from "./CwlPoolRoles";
import {
  createSeasonConfirmation,
  createdSeasonMessage,
  finishMonth,
  type SeasonState,
} from "./seasonFlow";
import { useDashboardPermission } from "./DashboardPermissions";

type Props = {
  actorId?: string;
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
  actorId = "",
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
  const season = lifecycleSeason(seasons, memberSeason.season_id);
  const [label, setLabel] = useState("");
  const [createLabel, setCreateLabel] = useState<string | null>(null);
  const [startReview, setStartReview] = useState<StartOperation | null>(null);
  const [recovery, setRecovery] = useState<StartOperation | null>(() =>
    actorId ? readStartOperation(actorId) : null,
  );
  const [startReadiness, setStartReadiness] =
    useState<LifecycleReadiness | null>(null);
  const [startReadError, setStartReadError] = useState("");
  useEffect(() => {
    setStartReview(null);
    if (!allowed) {
      clearStartOperation(actorId);
      setRecovery(null);
    } else setRecovery(actorId ? readStartOperation(actorId) : null);
  }, [actorId, allowed]);
  useEffect(() => {
    let active = true;
    setStartReadiness(null);
    setStartReadError("");
    if (startReview)
      void loadLifecycleReadiness(startReview.seen.season_id)
        .then((value) => {
          if (active) setStartReadiness(value);
        })
        .catch(() => {
          if (active)
            setStartReadError(
              "Season status unavailable. Refresh before retrying.",
            );
        });
    return () => {
      active = false;
    };
  }, [startReview?.seen.season_id, startReview?.cycle]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const createdId = useRef("");
  const [roleBusy, setRoleBusy] = useState(false);
  const [roleDirty, setRoleDirty] = useState(false);
  const current = seasons.find((item) => item.id === memberSeason.season_id);
  // One target month: the month after the member season, else after the newest.
  const target = nextMonthCycle(
    season
      ? [season]
      : seasons.filter(
          (item) => !item.history_only && item.status !== "archived",
        ),
  );
  const targetName = seasonMonthLabel({ label: target });
  const targetSeason = seasons.find((item) => seasonMonth(item) === target);
  const canCreate = !targetSeason;
  const canFinish =
    !!current &&
    (!targetSeason ||
      (targetSeason.id !== current.id && targetSeason.status !== "archived"));
  const signup = useSignupAction(season, onRefresh);
  const [readEpoch, setReadEpoch] = useState(0);
  const [readiness, setReadiness] = useState<LifecycleReadiness | null>(null);
  const [readError, setReadError] = useState("");
  const [reminders, setReminders] = useState<CampaignState | null>(null);
  useEffect(() => {
    let active = true;
    setReadiness(null);
    setReminders(null);
    setReadError("");
    if (!season || !allowed) return;
    void loadLifecycleReadiness(season.id)
      .then((value) => {
        if (active) setReadiness(value);
      })
      .catch(() => {
        if (active)
          setReadError(
            "Season status unavailable. Refresh before starting next month.",
          );
      });
    void api<CampaignState>(`/seasons/${season.id}/manage-reminders`)
      .then((value) => {
        if (active) setReminders(value);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [
    season?.id,
    season?.signup_open,
    season?.status,
    memberSeason.revision,
    allowed,
    readEpoch,
  ]);
  const warning =
    reminders?.signup_gate?.season_id === season?.id ||
    reminders?.signup_gate?.status === "unavailable"
      ? signupGateWarning(reminders)
      : "";
  const working = busy || roleBusy || signup.busy;
  useEffect(() => {
    onDirty?.(roleDirty || !!label.trim());
    return () => onDirty?.(false);
  }, [roleDirty, label, onDirty]);
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
    createdId.current = "";
    const chosen = createLabel;
    setCreateLabel(null);
    try {
      const result = await api<Season & { copied_clan_count: number }>(
        "/seasons",
        "POST",
        { label: chosen, signup_open: false },
      );
      setNotice(
        createdSeasonMessage(
          seasonMonthLabel(result),
          result.copied_clan_count,
        ),
      );
      setLabel("");
      try {
        await onRefresh();
        onSeasonChange(String(result.id));
      } catch {
        createdId.current = String(result.id);
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
  async function finish() {
    if (pending.current || !allowed || !startReview) return;
    const operation = startReview;
    if (!saveStartOperation(operation)) {
      setError(
        "Could not retain the Start request in this tab. No changes made.",
      );
      return;
    }
    pending.current = true;
    setRecovery(operation);
    setBusy(true);
    setError("");
    setRefreshFailed(false);
    setStartReview(null);
    try {
      await finishMonth(operation.cycle, operation.openSignups, operation.seen);
      clearStartOperation(actorId);
      setRecovery(null);
      setNotice(
        `${seasonMonthLabel({ label: operation.cycle })} is shown to members${operation.openSignups ? " and signups are open" : ""}. The previous month is locked.`,
      );
    } catch (cause) {
      const error =
        cause instanceof Error ? cause.message : "Could not start the month.";
      const retained = { ...operation, error };
      saveStartOperation(retained);
      setRecovery(retained);
      setError(error);
    } finally {
      try {
        await onRefresh();
      } catch {
        setError((value) =>
          `${value} The season list could not refresh.`.trim(),
        );
        setRefreshFailed(true);
      }
      pending.current = false;
      setBusy(false);
    }
  }
  async function retryRefresh() {
    if (pending.current || signup.busy || roleBusy) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setRefreshFailed(false);
    try {
      await onRefresh();
      setReadEpoch((value) => value + 1);
      if (createdId.current) {
        const created = createdId.current;
        createdId.current = "";
        onSeasonChange(created);
      }
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
        <Button
          variant="secondary"
          disabled={working}
          onClick={() => void retryRefresh()}
        >
          Refresh
        </Button>
      </CwlPageHeader>
      <LoadError
        message={error || readError}
        disabled={working}
        onRetry={
          refreshFailed || readError ? () => void retryRefresh() : undefined
        }
      />
      {notice && (
        <p className="notice success" role="status">
          {notice}
        </p>
      )}
      <div className="card">
        <h2>
          {season
            ? seasonMonthLabel(season)
            : memberSeason.season_id !== null
              ? "Member season unavailable"
              : "No season"}
        </h2>
        {!season && memberSeason.season_id !== null && (
          <p role="alert">Refresh before changing the member season.</p>
        )}
        {season && (
          <>
            <p>
              {memberSeason.season_id === season.id
                ? "Shown to members"
                : "Not shown to members"}
            </p>
            <ol className="season-lifecycle" aria-label="Season steps">
              {lifecycleStepStates(
                season,
                memberSeason.season_id === season.id,
                !!readiness?.published,
              ).map((step) => (
                <li
                  key={step.label}
                  aria-current={step.state === "Current" ? "step" : undefined}
                >
                  {step.label} · {step.state}
                </li>
              ))}
            </ol>
            {warning && (
              <p className="notice warning" role="status">
                {warning}
              </p>
            )}
            {allowed &&
              season.status !== "archived" &&
              (!readiness?.published ||
                memberSeason.season_id !== season.id) && (
                <Button
                  variant="primary"
                  disabled={working}
                  onClick={() =>
                    void signup.begin(
                      memberSeason.season_id !== season.id && season.signup_open
                        ? "fix"
                        : season.signup_open
                          ? "close"
                          : "open",
                    )
                  }
                >
                  {memberSeason.season_id !== season.id
                    ? "Show and open signups"
                    : season.signup_open
                      ? "Close signups"
                      : "Open signups"}
                </Button>
              )}
            {signup.visibilityCheck}
            {signup.error && <p role="alert">{signup.error}</p>}
            {signup.notice && <p role="status">{signup.notice}</p>}
          </>
        )}
      </div>
      {seasons.some(
        (item) =>
          item.id !== season?.id &&
          (!season || seasonMonth(item) < seasonMonth(season)),
      ) && (
        <section aria-label="Older seasons">
          <h2>Older seasons</h2>
          <ul>
            {monthSeasons(seasons)
              .filter(
                (item) =>
                  item.id !== season?.id &&
                  (!season || seasonMonth(item) < seasonMonth(season)),
              )
              .map((item) => (
                <li key={item.id}>
                  {seasonMonthLabel(item)} ·{" "}
                  {item.status === "archived" ? "Locked" : "Not locked"}
                </li>
              ))}
          </ul>
        </section>
      )}
      {allowed && (memberSeason.season_id === null || !!current) && (
        <div className="card">
          <h2>Next month</h2>
          <div className="staff-row">
            {canCreate && (
              <Button
                icon={Plus}
                variant={canFinish ? "secondary" : "primary"}
                disabled={working}
                onClick={() => setCreateLabel(targetName)}
              >
                {`Create ${targetName}`}
              </Button>
            )}
            {canFinish && current && (
              <Button
                variant={readiness?.published ? "primary" : "secondary"}
                disabled={working || !!recovery}
                onClick={() =>
                  setStartReview({
                    actor: actorId,
                    cycle: target,
                    openSignups: false,
                    seen: {
                      season_id: current.id,
                      revision: memberSeason.revision,
                    },
                  })
                }
              >
                {`Start ${targetName}`}
              </Button>
            )}
          </div>
          {current && (
            <p>{`Members see ${targetName}. ${seasonMonthLabel(current)} stays saved.`}</p>
          )}
          <details>
            <summary>Other name</summary>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const typed = label.trim();
                if (working || typed.length < 3) return;
                const month = seasonMonth({ label: typed });
                if (
                  month &&
                  seasons.some((item) => seasonMonth(item) === month)
                )
                  setError(
                    `${seasonMonthLabel({ label: month })} already exists.`,
                  );
                else setCreateLabel(typed);
              }}
            >
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
          </details>
        </div>
      )}
      {createLabel && (
        <ConfirmDialog
          heading="Create season"
          text={createSeasonConfirmation(
            seasonMonthLabel({ label: createLabel }),
            seasons.length === 0,
          )}
          confirmLabel={`Create ${seasonMonthLabel({ label: createLabel })}`}
          onCancel={() => setCreateLabel(null)}
          onConfirm={() => void save()}
          disabled={working || !allowed}
        />
      )}
      {recovery && (
        <section className="card" aria-label="Unfinished Start">
          <h2>{`Unfinished Start ${seasonMonthLabel({ label: recovery.cycle })}`}</h2>
          <p>{recovery.error || "Check the saved steps before retrying."}</p>
          <Button
            variant="secondary"
            disabled={working || !allowed}
            onClick={() => setStartReview(recovery)}
          >
            {`Retry Start ${seasonMonthLabel({ label: recovery.cycle })}`}
          </Button>
        </section>
      )}
      {startReview && (
        <ConfirmDialog
          heading={`${recovery ? "Retry Start" : "Start"} ${seasonMonthLabel({ label: startReview.cycle })}`}
          text={`Show ${seasonMonthLabel({ label: startReview.cycle })} to members, then lock the previous month. Completed steps stay saved.`}
          confirmLabel={`${recovery ? "Retry Start" : "Start"} ${seasonMonthLabel({ label: startReview.cycle })}`}
          onCancel={() => setStartReview(null)}
          onConfirm={() => void finish()}
          disabled={
            working ||
            !allowed ||
            !startReadiness ||
            startReadiness.blockers.length > 0 ||
            !!startReadError
          }
        >
          {(!startReadiness ||
            startReadError ||
            startReadiness.blockers.length > 0) && (
            <div role="alert">
              <strong>Finish these first</strong>
              <p>
                {startReadError ||
                  (!startReadiness
                    ? "Checking results and bonuses…"
                    : startReadiness.blockers.join(", "))}
              </p>
            </div>
          )}
          <label>
            <input
              type="checkbox"
              checked={startReview.openSignups}
              onChange={(event) =>
                setStartReview({
                  ...startReview,
                  openSignups: event.target.checked,
                })
              }
            />
            {`Open ${seasonMonthLabel({ label: startReview.cycle })} signups now`}
          </label>
        </ConfirmDialog>
      )}
      {signup.dialog}
      <CwlPoolRoles onBusy={setRoleBusy} onDirty={setRoleDirty} />
      <CwlNextLink
        label="Build roster"
        route={{ view: "roster", season: seasonId }}
        onNext={onClans}
        disabled={working || !seasonId}
      />
    </section>
  );
}
