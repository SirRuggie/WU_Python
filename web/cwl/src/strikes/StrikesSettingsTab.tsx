import StrikeSettingsEditor from "../StrikeSettingsEditor";
import type { Settings } from "./types";

export default function StrikesSettingsTab({
  settings,
  error,
  onSaved,
  onDirty,
  onBusy,
  onRetry,
}: {
  settings: Settings | null;
  error: string;
  onSaved: (settings: Settings) => void;
  onDirty: (dirty: boolean) => void;
  onBusy: (busy: boolean) => void;
  onRetry: () => void;
}) {
  return settings ? (
    <StrikeSettingsEditor
      settings={settings}
      onSaved={onSaved}
      onDirty={onDirty}
      onBusy={onBusy}
    />
  ) : (
    <p role="status">
      {error ? (
        <button onClick={onRetry}>Retry settings</button>
      ) : (
        "Loading settings…"
      )}
    </p>
  );
}
