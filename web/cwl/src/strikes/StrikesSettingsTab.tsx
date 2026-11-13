import StrikeSettingsEditor from "../StrikeSettingsEditor";
import type { Settings } from "./types";

export default function StrikesSettingsTab({
  settings,
  error,
  onSaved,
  onDirty,
  onBusy,
}: {
  settings: Settings | null;
  error: string;
  onSaved: (settings: Settings) => void;
  onDirty: (dirty: boolean) => void;
  onBusy: (busy: boolean) => void;
}) {
  return settings ? (
    <StrikeSettingsEditor
      settings={settings}
      onSaved={onSaved}
      onDirty={onDirty}
      onBusy={onBusy}
    />
  ) : (
    !error && <p role="status">Loading settings…</p>
  );
}
