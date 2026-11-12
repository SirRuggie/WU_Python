import { useEffect, useId } from "react";
import InfractionFields, { useInfractionDraft } from "./InfractionFields";
import type { BonusReview } from "./bonusRaffle";
import type { Infractions } from "./useInfractions";

/** What staff changed in the editor; the Details footer Save writes it. */
export type InfractionsDraft = {
  dirty: boolean;
  flags: string[];
  reason: string;
};
export const noInfractionsDraft: InfractionsDraft = {
  dirty: false,
  flags: [],
  reason: "",
};

type Props = {
  tag: string;
  clanTag: string;
  infractions: Infractions;
  /** Changes when staff discard, so the editor starts again from the saved review. */
  resetKey: number;
  busy: boolean;
  error: string;
  notice: string;
  onDraft: (draft: InfractionsDraft) => void;
};

type EditorProps = {
  review: BonusReview | null | undefined;
  readOnly: boolean;
  busy: boolean;
  onDraft: (draft: InfractionsDraft) => void;
};

function InfractionsEditor({ review, readOnly, busy, onDraft }: EditorProps) {
  const { flags, setFlags, reason, setReason, dirty } =
    useInfractionDraft(review);
  useEffect(() => {
    onDraft({ dirty, flags, reason });
    return () => onDraft(noInfractionsDraft);
  }, [dirty, flags, reason, onDraft]);
  return (
    <InfractionFields
      flags={flags}
      reason={reason}
      disabled={busy || readOnly}
      onFlags={setFlags}
      onReason={setReason}
    />
  );
}

/** Lazy infractions inside the player Details sheet; its footer Save writes them. */
export default function InfractionsSection({
  tag,
  clanTag,
  infractions,
  resetKey,
  busy,
  error,
  notice,
  onDraft,
}: Props) {
  const titleId = useId();
  const { data, state, load, lock } = infractions;
  const account = data?.accounts.find((item) => item.tag === tag);
  const locked = lock(clanTag);

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
            onDraft={onDraft}
          />
        </>
      )}
      {error && (
        <p className="notice error" role="alert">
          Infractions not saved · {error}
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
