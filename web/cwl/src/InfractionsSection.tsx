import { useEffect, useId, useRef, useState } from "react";
import InfractionFields, { useInfractionDraft } from "./InfractionFields";
import type { BonusReview } from "./bonusRaffle";
import type { Infractions } from "./useInfractions";

type Props = {
  tag: string;
  clanName: string;
  clanTag: string;
  infractions: Infractions;
  /** Changes when staff discard, so the editor starts again from the saved review. */
  resetKey: number;
  onState: (dirty: boolean, busy: boolean) => void;
};

type EditorProps = {
  review: BonusReview | null | undefined;
  readOnly: boolean;
  busy: boolean;
  onState: (dirty: boolean) => void;
  onSave: (flags: string[], reason: string) => void;
};

function InfractionsEditor({
  review,
  readOnly,
  busy,
  onState,
  onSave,
}: EditorProps) {
  const { flags, setFlags, reason, setReason, dirty, reset } =
    useInfractionDraft(review);
  useEffect(() => {
    onState(dirty);
    return () => onState(false);
  }, [dirty, onState]);
  return (
    <>
      <InfractionFields
        flags={flags}
        reason={reason}
        disabled={busy || readOnly}
        onFlags={setFlags}
        onReason={setReason}
      />
      {!readOnly && (
        <div className="participation-infractions-actions">
          <button type="button" disabled={busy || !dirty} onClick={reset}>
            Cancel
          </button>
          <button
            type="button"
            className="primary"
            disabled={busy || !dirty || (!!reason && !reason.trim())}
            onClick={() => onSave(flags, reason.trim())}
          >
            {busy ? "Saving…" : "Save infractions"}
          </button>
        </div>
      )}
    </>
  );
}

/** Lazy infractions inside the player Details sheet. */
export default function InfractionsSection({
  tag,
  clanName,
  clanTag,
  infractions,
  resetKey,
  onState,
}: Props) {
  const titleId = useId();
  const { data, state, load, save, lock } = infractions;
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const account = data?.accounts.find((item) => item.tag === tag);
  const locked = lock(clanTag);

  useEffect(() => {
    onState(dirty, busy);
  }, [dirty, busy, onState]);
  useEffect(() => () => onState(false, false), [onState]);

  const submit = async (flags: string[], reason: string) => {
    if (pending.current || locked) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await save(tag, flags, reason);
      setNotice(`Infractions saved · ${clanName} eligibility updated.`);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Infractions could not be saved. Try again.",
      );
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };

  return (
    <section className="participation-infractions" aria-labelledby={titleId}>
      <h3 id={titleId}>Infractions</h3>
      {!data && state !== "failed" && <p>Loading infractions…</p>}
      {((!data && state === "failed") || (data && !account)) && (
        <p role="alert">
          Infractions unavailable ·{" "}
          <button type="button" onClick={load}>
            Retry
          </button>
        </p>
      )}
      {account && (
        <>
          {locked === "draw" && <p>Draw saved · read only</p>}
          {locked === "locked" && <p>Read only</p>}
          <InfractionsEditor
            key={`${resetKey}:${account.bonus_review?.revision ?? 0}:${account.bonus_review?.updated_at ?? ""}`}
            review={account.bonus_review}
            readOnly={!!locked}
            busy={busy}
            onState={setDirty}
            onSave={(flags, reason) => void submit(flags, reason)}
          />
        </>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="notice success" role="status">
          {notice}
        </p>
      )}
    </section>
  );
}
