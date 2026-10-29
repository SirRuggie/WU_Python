import TownHallIcon from "../TownHallIcon";

/** Fake presentation only: no API imports, real forms, or submit handlers. */
export default function Practice({
  step,
  advance,
}: {
  step: number;
  advance: () => void;
}) {
  if (step < 4 || step > 8) return null;
  return (
    <section
      className={`tour-practice${step === 8 ? " is-saved" : ""}`}
      aria-label="Practice signup"
    >
      <strong className="tour-practice-badge">
        PRACTICE · nothing is saved
      </strong>
      <h2>
        {step === 8
          ? "✓ You're signed up"
          : step === 7
            ? "Confirm your signup"
            : "Sign up"}
      </h2>
      {step <= 6 && (
        <>
          <button
            type="button"
            className="tour-demo-account"
            data-tour-target="demo-account"
            onClick={step === 4 ? advance : undefined}
          >
            <TownHallIcon level={15} />
            <span>Demo Barbarian · TH15</span>
            <span aria-hidden="true">{step > 4 ? "✓" : "□"}</span>
          </button>
          <div className="tour-pools">
            <button type="button" disabled>
              Main CWL
            </button>
            <button
              type="button"
              data-tour-target="demo-pool"
              aria-pressed={step >= 6}
              onClick={step === 5 ? advance : undefined}
            >
              Lazy CWL
            </button>
          </div>
          <button
            type="button"
            data-tour-target="demo-review"
            onClick={step === 6 ? advance : undefined}
          >
            Review
          </button>
        </>
      )}
      {step === 7 && (
        <>
          <p>Demo Barbarian · TH15 · Lazy CWL</p>
          <button
            type="button"
            data-tour-target="demo-confirm"
            onClick={advance}
          >
            Confirm
          </button>
        </>
      )}
      {step === 8 && <p>Demo Barbarian · TH15 · Lazy CWL</p>}
      <button type="submit" disabled className="tour-real-submit">
        Real signup disabled in practice
      </button>
    </section>
  );
}
