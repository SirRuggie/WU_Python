import type { Dispatch, SetStateAction } from "react";
import BandStatusSummary from "./BandStatusSummary";
import TownHallBasesFields from "./TownHallBasesFields";
import ManagementFieldInput from "./ManagementFieldInput";
import TownHallAddFields, { duplicateTownHall } from "./TownHallAddFields";
import type {
  ManagementDocument,
  ManagementField,
  ManagementSection,
  ManagementValue,
} from "./serverManagement";
import "./TownHallEditor.css";

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
  onOpenRecord?: (endpoint: string) => void;
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
  onOpenRecord,
  setFieldPage,
  setMobilePane,
  setDocument,
  setDraft,
  setNotice,
}: Props) {
  const townHalls = document.id === "town_halls";
  const creating = townHalls && !!document.create;
  const duplicate =
    creating && duplicateTownHall(document, Number(draft.level));
  const grouped = document.fields.some((field) => field.group);
  const groups = new Map<string, ManagementField[]>();
  for (const field of document.fields) {
    const name = field.group || "";
    groups.set(name, [...(groups.get(name) || []), field]);
  }
  function change(key: string, value: ManagementValue) {
    const normalized =
      townHalls && ["min", "max"].includes(key) && value === ""
        ? null
        : townHalls && key === "lowest_fwa_town_hall" && value !== ""
          ? Number(value)
          : value;
    setDraft((current) => ({ ...current, [key]: normalized }));
    setNotice("");
  }
  function renderField(field: ManagementField) {
    return (
      <ManagementFieldInput
        key={field.key + ":" + (document.member_refresh || "")}
        townHallLevel={document.level}
        memberRoles={
          document.fields.find((item) => item.key === "role_ids")?.options
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
        onChange={(value) => change(field.key, value)}
      />
    );
  }
  function renderGroup(fields: ManagementField[]) {
    const pair =
      townHalls &&
      fields.some((field) => field.key === "min") &&
      fields.some((field) => field.key === "max");
    const low = draft.min,
      high = draft.max;
    const preview =
      typeof low === "number" &&
      typeof high === "number" &&
      Number.isFinite(low) &&
      Number.isFinite(high) &&
      low > 0 &&
      low < high;
    return (
      <div className="manage-fields">
        {fields
          .filter((field) => !pair || !["min", "max"].includes(field.key))
          .map(renderField)}
        {pair && (
          <div className="town-hall-weight-group">
            <div className="town-hall-weight-pair">
              {fields
                .filter((field) => ["min", "max"].includes(field.key))
                .map(renderField)}
            </div>
            {preview && (
              <p className="small">
                Shows as {low / 1000}k – {high / 1000}k
              </p>
            )}
          </div>
        )}
      </div>
    );
  }
  return (
    <form
      className={townHalls ? "manage-town-hall-editor" : undefined}
      onSubmit={(event) => {
        event.preventDefault();
        if (!duplicate) onSave();
      }}
    >
      {document.readonly && operationsWorkspace ? (
        <BandStatusSummary fields={document.fields} />
      ) : (
        <fieldset disabled={busy || document.readonly} aria-busy={busy}>
          <legend className="manage-sr-only">{selected.label} settings</legend>
          {creating ? (
            <TownHallAddFields
              document={document}
              draft={draft}
              disabled={busy || !!document.readonly}
              change={change}
              openRecord={onOpenRecord}
            />
          ) : document.base_management ? (
            <TownHallBasesFields
              document={document}
              draft={draft}
              renderField={renderField}
            />
          ) : grouped ? (
            <div className="manage-grouped-fields">
              {[...groups].map(([name, fields]) =>
                name ? (
                  <fieldset key={name} className="manage-field-group">
                    <legend>{name}</legend>
                    {renderGroup(fields)}
                  </fieldset>
                ) : (
                  <div key="ungrouped">{renderGroup(fields)}</div>
                ),
              )}
            </div>
          ) : (
            <>
              {document.fields.length > 6 && (
                <label className="manage-record-picker">
                  Message or setting to edit
                  <select
                    value={fieldPage}
                    onChange={(event) =>
                      setFieldPage(Number(event.target.value))
                    }
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
                ).map(renderField)}
              </div>
            </>
          )}
          {document.help && <p className="small">{document.help}</p>}
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
              : dirty || creating
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
              className={dirty || creating ? "primary" : undefined}
              type="submit"
              disabled={
                busy ||
                (!dirty && !creating) ||
                duplicate ||
                publishDirty ||
                conflict ||
                !!statusUrl
              }
            >
              {document.submit_label || "Save changes"}
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
