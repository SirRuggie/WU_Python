type Props = {
  poolLabel: string;
  count: number;
  busy: boolean;
  onChange: (step: 1 | 2) => void;
};
export default function SignupReviewHeading({
  poolLabel,
  count,
  busy,
  onChange,
}: Props) {
  return (
    <>
      <div className="signup-review-heading">
        <h3>{poolLabel}</h3>
        <button
          type="button"
          aria-label="Change CWL"
          disabled={busy}
          onClick={() => onChange(1)}
        >
          Change CWL
        </button>
      </div>
      <div className="signup-review-heading">
        <p>
          {count} {count === 1 ? "account" : "accounts"} selected. Staff will
          assign your hosting clans.
        </p>
        <button
          type="button"
          aria-label="Change accounts"
          disabled={busy}
          onClick={() => onChange(2)}
        >
          Change accounts
        </button>
      </div>
    </>
  );
}
