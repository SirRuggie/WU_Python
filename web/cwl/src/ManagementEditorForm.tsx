import type { Dispatch, SetStateAction } from "react";
import BandStatusSummary from "./BandStatusSummary";
import ManagementFieldInput from "./ManagementFieldInput";
import type {
  ManagementDocument,
  ManagementSection,
  ManagementValue,
} from "./serverManagement";

type Props = {
  selected: ManagementSection;
  document: ManagementDocument;
  draft: Record<string, ManagementValue>;
  busy: boolean;
  dirty: boolean;
  conflict: boolean;
  publishDirty: boolean;
  statusUrl: string;
  fieldPage: number;
  compactPreview: boolean;
  operationsWorkspace: boolean;
  onSave: (review?: boolean) => void;
  setFieldPage: Dispatch<SetStateAction<number>>;
  setMobilePane: Dispatch<SetStateAction<"edit" | "preview">>;
  setDocument: Dispatch<SetStateAction<ManagementDocument | null>>;
  setDraft: Dispatch<SetStateAction<Record<string, ManagementValue>>>;
  setNotice: Dispatch<SetStateAction<string>>;
};

export default function ManagementEditorForm({
  selected,
  document,
  draft,
  busy,
  dirty,
  conflict,
  publishDirty,
  statusUrl,
  fieldPage,
  compactPreview,
  operationsWorkspace,
  onSave,
  setFieldPage,
  setMobilePane,
  setDocument,
  setDraft,
  setNotice,
}: Props) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      {document.readonly && operationsWorkspace ? (
        <BandStatusSummary fields={document.fields} />
      ) : (
        <fieldset disabled={busy || document.readonly} aria-busy={busy}>
          <legend className="manage-sr-only">{selected.label} settings</legend>
          {document.fields.length > 6 && (
            <label className="manage-record-picker">
              Message or setting to edit
              <select
                value={fieldPage}
                onChange={(event) => setFieldPage(Number(event.target.value))}
              >
                {Array.from(
                  { length: Math.ceil(document.fields.length / 4) },
                  (_, index) => (
                    <option key={index} value={index}>
                      {document.fields[index * 4].label}
                    </option>
                  ),
                )}
              </select>
              <small>Save applies all edits.</small>
            </label>
          )}
          <div className="manage-fields">
            {(document.fields.length > 6
              ? document.fields.slice(fieldPage * 4, fieldPage * 4 + 4)
              : document.fields
            ).map((field) => (
              <ManagementFieldInput
                key={field.key + ":" + (document.member_refresh || "")}
                memberRoles={
                  document.fields.find((item) => item.key === "role_ids")
                    ?.options
                }
                onMemberOptions={(options) =>
                  setDocument((current) =>
                    current
                      ? {
                          ...current,
                          fields: current.fields.map((item) =>
                            item.key === field.key
                              ? {
                                  ...item,
                                  options: [
                                    ...new Map(
                                      [...(item.options || []), ...options].map(
                                        (option) => [option.value, option],
                                      ),
                                    ).values(),
                                  ],
                                }
                              : item,
                          ),
                        }
                      : current,
                  )
                }
                revision={document.revision}
                field={field}
                value={draft[field.key]}
                disabled={busy || !!document.readonly}
                onChange={(value) => {
                  setDraft((current) => ({
                    ...current,
                    [field.key]: value,
                  }));
                  setNotice("");
                }}
              />
            ))}
          </div>
        </fieldset>
      )}
      {!document.readonly && !document.action_only && (
        <div className="manage-save">
          <span
            className={busy ? "working-status" : undefined}
            aria-live="polite"
          >
            {busy
              ? "Working…"
              : dirty
                ? "Changes not saved"
                : "All changes saved"}
          </span>
          <div>
            {document.preview_supported &&
              !compactPreview &&
              !operationsWorkspace && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setMobilePane("preview");
                    onSave(true);
                  }}
                >
                  Preview
                </button>
              )}
            <button
              className="primary"
              type="submit"
              disabled={
                busy || !dirty || publishDirty || conflict || !!statusUrl
              }
            >
              Save changes
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
