import { useEffect, useRef, useState } from "react";
import { api, type Season } from "./api";
import ConfirmDialog from "./ConfirmDialog";
import { useDashboardPermission } from "./DashboardPermissions";
import {
  applySignupPlan,
  signupPlan,
  type SeasonState,
  type SignupAction,
} from "./seasonFlow";

export default function useSignupAction(
  season: Season | undefined,
  onChanged: () => Promise<void>,
) {
  const allowed = useDashboardPermission("cwl_settings");
  const [state, setState] = useState<SeasonState | null>(null);
  const [review, setReview] = useState<{
    season: Season;
    state: SeasonState;
    action: SignupAction;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const submitting = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    const id = ++generation.current;
    setState(null);
    setReview(null);
    setError("");
    setNotice("");
    void api<SeasonState>("/seasons")
      .then((value) => {
        if (id === generation.current) setState(value);
      })
      .catch(() => {
        /* Opening an action always performs a fresh read. */
      });
    return () => {
      generation.current++;
    };
  }, [season?.id, season?.signup_open]);
  async function begin(action: SignupAction) {
    if (
      !season ||
      !allowed ||
      busy ||
      submitting.current ||
      season.status === "archived"
    )
      return;
    submitting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const id = generation.current;
    try {
      const fresh = await api<SeasonState>("/seasons");
      if (id !== generation.current) return;
      setState(fresh);
      const selected = fresh.seasons.find((item) => item.id === season.id);
      if (!selected || selected.status === "archived")
        throw new Error("Season is unavailable or archived. Refresh the page.");
      setReview({ season: selected, state: fresh, action });
    } catch (cause) {
      if (id === generation.current)
        setError(
          cause instanceof Error ? cause.message : "Could not check season.",
        );
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  async function confirm() {
    if (!review || !allowed || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    const captured = review;
    setReview(null);
    try {
      await applySignupPlan(captured.season, captured.state, captured.action);
      setNotice(
        captured.action === "fix" && captured.season.signup_open
          ? "Season shown to members."
          : `Signups ${captured.action === "close" ? "closed" : "opened"}.`,
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not change signups.",
      );
    } finally {
      // Includes 409 and partial success: read only, never retry either write.
      try {
        setState(await api<SeasonState>("/seasons"));
        await onChanged();
      } catch {
        setError(
          (current) =>
            `${current ? `${current} ` : ""}Could not refresh season status. Refresh before trying again.`,
        );
      }
      submitting.current = false;
      setBusy(false);
    }
  }
  const hiddenOpen =
    !!season?.signup_open &&
    !!state &&
    state.member_season.season_id !== season.id;
  return {
    busy,
    error,
    notice,
    hiddenOpen,
    begin,
    dialog: review ? (
      <ConfirmDialog
        heading="Signup visibility"
        text={signupPlan(review.season, review.state, review.action).text}
        confirmLabel={
          signupPlan(review.season, review.state, review.action).label
        }
        onCancel={() => setReview(null)}
        onConfirm={() => void confirm()}
        disabled={busy || !allowed}
      />
    ) : null,
  };
}
