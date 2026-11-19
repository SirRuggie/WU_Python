import type { ReactNode } from "react";
import type {
  ManagementDocument,
  ManagementField,
  ManagementValue,
} from "./serverManagement";
import TownHallBaseImagePreview from "./TownHallBaseImagePreview";
import "./TownHallBasesFields.css";

export default function TownHallBasesFields({
  document,
  draft,
  renderField,
}: {
  document: ManagementDocument;
  draft: Record<string, ManagementValue>;
  renderField: (field: ManagementField) => ReactNode;
}) {
  const groups = ["Town Hall", "Base images", "Merged", "Non-merged"];
  const values = Object.fromEntries(
    document.fields.map((field) => [field.key, field.value]),
  );
  function readonlyTownHall() {
    const emoji = String(values.emoji || "").match(/^<a?:([^:>]+):\d+>$/)?.[1];
    return (
      <>
        <p className="town-hall-readonly-emoji">
          {document.emoji_url && (
            <img src={document.emoji_url} width={32} height={32} alt="" />
          )}
          <span>{emoji || "None"}</span>
        </p>
        {typeof values.min === "number" && typeof values.max === "number" && (
          <p>
            {values.min / 1000}k – {values.max / 1000}k
          </p>
        )}
        <p className="small">
          Only server admins can change the emoji and weight.
        </p>
      </>
    );
  }
  function editableTownHall(fields: ManagementField[]) {
    const low = draft.min,
      high = draft.max;
    return (
      <div className="manage-fields">
        {fields
          .filter((field) => !["min", "max"].includes(field.key))
          .map(renderField)}
        <div className="town-hall-weight-group">
          <div className="town-hall-weight-pair">
            {fields
              .filter((field) => ["min", "max"].includes(field.key))
              .map(renderField)}
          </div>
          {typeof low === "number" &&
            typeof high === "number" &&
            low > 0 &&
            low < high && (
              <p className="small">
                Shows as {low / 1000}k – {high / 1000}k
              </p>
            )}
        </div>
      </div>
    );
  }
  function readonlyBase(field: ManagementField) {
    const value = String(field.value || "");
    if (field.group === "Base images")
      return (
        <div key={field.key}>
          <p>{field.label}</p>
          <TownHallBaseImagePreview value={value} label={field.label} />
        </div>
      );
    return (
      <div className="town-hall-readonly-field" key={field.key}>
        <p className="small">{field.label}</p>
        {field.key.endsWith(".link") && value ? (
          <a href={value} target="_blank" rel="noopener noreferrer">
            {value}
          </a>
        ) : (
          <p>{value || "Not set"}</p>
        )}
      </div>
    );
  }
  return (
    <div className="town-hall-bases-groups">
      {groups.map((group) => {
        const fields = document.fields.filter((field) => field.group === group);
        const readonly = !!document.section_readonly?.[group];
        const variant = group === "Merged" || group === "Non-merged";
        const shown = !!document.base_status?.[group];
        return (
          <fieldset
            key={group}
            className={`manage-field-group town-hall-group-${group === "Town Hall" ? "town" : group === "Base images" ? "images" : "variant"}`}
          >
            <legend>
              {group}
              {variant && (
                <span
                  className={`town-hall-base-visibility ${shown ? "is-shown" : ""}`}
                >
                  {shown ? "Shown to members" : "Hidden from members"}
                </span>
              )}
            </legend>
            {variant && !shown && (
              <p className="small">
                Add a base link to show this variant to members.
              </p>
            )}
            {group === "Town Hall" ? (
              readonly ? (
                readonlyTownHall()
              ) : (
                editableTownHall(fields)
              )
            ) : (
              <div
                className={
                  group === "Base images"
                    ? "town-hall-base-image-grid"
                    : "manage-fields"
                }
              >
                {fields.map((field) =>
                  readonly ? readonlyBase(field) : renderField(field),
                )}
              </div>
            )}
            {readonly && group !== "Town Hall" && (
              <p className="small">Only base managers can change bases.</p>
            )}
          </fieldset>
        );
      })}
    </div>
  );
}
