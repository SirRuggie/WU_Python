import type { ManagementDocument, ManagementValue } from "./serverManagement";
import ManagementFieldInput from "./ManagementFieldInput";
import TownHallEmojiPicker from "./TownHallEmojiPicker";
import useTownHallEmojiSuggestion from "./useTownHallEmojiSuggestion";

export function duplicateTownHall(document: ManagementDocument, level: number) {
  return (
    document.documents?.some(
      (record) => record.list_role === "level" && record.id === String(level),
    ) || false
  );
}

export default function TownHallAddFields({
  document,
  draft,
  disabled,
  change,
  openRecord,
}: {
  document: ManagementDocument;
  draft: Record<string, ManagementValue>;
  disabled: boolean;
  change: (key: string, value: ManagementValue) => void;
  openRecord?: (endpoint: string) => void;
}) {
  const level = Number(draft.level);
  const suggestion = useTownHallEmojiSuggestion(level, (emoji) =>
    change("emoji", emoji),
  );
  const levelField = document.fields.find((field) => field.key === "level");
  const duplicate = duplicateTownHall(document, level);
  return (
    <div className="town-hall-create-fields">
      {levelField && (
        <div>
          <ManagementFieldInput
            field={levelField}
            value={draft.level}
            onChange={(value) => change("level", value)}
            disabled={disabled}
            revision={document.revision}
          />
          {duplicate && (
            <p className="error" role="alert">
              This Town Hall is already in the list. Open it to edit.{" "}
              <a
                href={`/manage/town-halls/${level}`}
                onClick={(event) => {
                  if (
                    openRecord &&
                    !event.defaultPrevented &&
                    event.button === 0 &&
                    !event.metaKey &&
                    !event.ctrlKey &&
                    !event.shiftKey &&
                    !event.altKey
                  ) {
                    event.preventDefault();
                    openRecord(`/manage/town-halls/${level}`);
                  }
                }}
              >
                Open Town Hall {level}
              </a>
            </p>
          )}
        </div>
      )}
      <TownHallEmojiPicker
        value={String(draft.emoji || "")}
        level={level}
        onChange={suggestion.choose}
        disabled={disabled}
        preloaded={suggestion.data}
        preloadPending={suggestion.loading}
        preloadStatus={suggestion.status}
        onLoaded={suggestion.recovered}
      />
      {suggestion.suggestion && (
        <p className="small">
          Found a bot emoji for this level. Save to confirm it.
        </p>
      )}
      {suggestion.status && (
        <p className="small" role="status">
          {suggestion.status}
        </p>
      )}
    </div>
  );
}
