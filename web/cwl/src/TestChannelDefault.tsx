export default function TestChannelDefault({
  checked,
  disabled,
  error,
  onChange,
  onReload,
}: {
  checked: boolean;
  disabled: boolean;
  error: string;
  onChange: (value: boolean) => void;
  onReload: () => void;
}) {
  return (
    <div className="test-channel-default">
      <label>
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />{" "}
        Make this the default
      </label>
      {error && (
        <p role="alert">
          Saved test channel unavailable: {error}{" "}
          <button disabled={disabled} onClick={onReload}>
            Reload saved channel
          </button>
        </p>
      )}
    </div>
  );
}
