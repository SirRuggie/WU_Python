/** One read-only destination cue, placed at the end of each CWL page. */
export default function CwlNextLink({
  label,
  onNext,
  disabled = false,
}: {
  label: string;
  onNext?: () => void;
  disabled?: boolean;
}) {
  if (!onNext) return null;
  return (
    <button
      type="button"
      className="cwl-next-cue"
      disabled={disabled}
      onClick={onNext}
    >
      Next: {label} ›
    </button>
  );
}
