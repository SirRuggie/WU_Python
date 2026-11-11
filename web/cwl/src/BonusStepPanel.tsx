import type { ReactNode, Ref } from "react";
import type { BonusStep, BonusStepState } from "./bonusStatus";

type Props = {
  id: BonusStep;
  number: number;
  label: string;
  state: BonusStepState;
  open: boolean;
  /** One line shown when a done step is closed. */
  summary: string;
  onChange: () => void;
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
};

/** One step of the bonus flow: the open panel, or a done step as one line. */
export default function BonusStepPanel({
  id,
  number,
  label,
  state,
  open,
  summary,
  onChange,
  headingRef,
  children,
}: Props) {
  if (!open) {
    if (state !== "done") return null;
    return (
      <p className="bonus-step-done" data-step-panel={id}>
        <span>
          <span aria-hidden="true">✓ </span>
          {label} · {summary}
        </span>
        <button
          type="button"
          className="bonus-inline-action"
          aria-label={`Change ${label}`}
          onClick={onChange}
        >
          Change
        </button>
      </p>
    );
  }
  return (
    <section
      className="bonus-flow bonus-step-panel"
      data-step-panel={id}
      aria-labelledby={`bonus-step-${id}`}
    >
      <h3 id={`bonus-step-${id}`} ref={headingRef} tabIndex={-1}>
        {number}. {label}
      </h3>
      {children}
    </section>
  );
}
