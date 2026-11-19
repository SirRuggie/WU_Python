import { useState, type MouseEvent } from "react";
import SearchPicker from "./SearchPicker";
import type { ManagementSection } from "./serverManagement";
import "./TownHallRecords.css";

function RecordIcon({ record }: { record: ManagementSection }) {
  const [failed, setFailed] = useState<string | null>(null);
  return record.emoji_url && failed !== record.emoji_url ? (
    <img
      src={record.emoji_url}
      width={32}
      height={32}
      alt=""
      onError={() => setFailed(record.emoji_url || null)}
    />
  ) : (
    <span className="town-hall-fallback" aria-hidden="true">
      TH {record.id}
    </span>
  );
}

export default function TownHallRecords({
  records,
  currentEndpoint,
  editor = false,
  mayLeave,
  open,
}: {
  records: ManagementSection[];
  currentEndpoint?: string;
  editor?: boolean;
  mayLeave: () => boolean | Promise<boolean>;
  open: (endpoint: string) => void;
}) {
  async function navigate(endpoint: string) {
    if (await mayLeave()) open(endpoint);
  }
  function follow(event: MouseEvent<HTMLAnchorElement>, endpoint: string) {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    void navigate(endpoint);
  }
  if (editor) {
    const current = records.find(
      (record) => record.endpoint === currentEndpoint,
    );
    return (
      <nav className="town-hall-switcher" aria-label="Town Halls">
        <a
          href="/manage/town-halls"
          onClick={(event) => follow(event, "/manage/town-halls")}
        >
          ← Town Halls
        </a>
        <SearchPicker
          label="Town Hall"
          value={currentEndpoint || ""}
          options={records
            .filter((record) => record.endpoint)
            .map((record) => ({
              value: record.endpoint!,
              label: record.label,
              icon:
                record.list_role === "level" ? (
                  <RecordIcon record={record} />
                ) : undefined,
            }))}
          onChange={(endpoint) => void navigate(endpoint)}
          placeholder={current?.label || "Select a Town Hall"}
          searchPlaceholder="Search Town Halls"
          emptyText="No matching Town Halls."
        />
      </nav>
    );
  }
  const add = records.find((record) => record.list_role === "add");
  const setting = records.find((record) => record.list_role === "setting");
  const fwa = records.filter((record) => record.list_group === "fwa");
  const bases = records.some((record) => record.bases_meta !== undefined);
  const other = records.filter((record) => record.list_group === "other");
  function rows(items: ManagementSection[], showMeta: boolean) {
    return (
      <div className="town-hall-record-list">
        {items.map((record) => (
          <a
            key={record.id}
            className={`town-hall-record ${bases && showMeta ? "has-bases" : ""}`}
            href={record.endpoint}
            onClick={(event) =>
              record.endpoint && follow(event, record.endpoint)
            }
          >
            <span className="town-hall-record-name">
              <RecordIcon record={record} />
              <span>{record.label}</span>
            </span>
            {showMeta && (
              <span
                className={
                  record.meta === "No weight range"
                    ? "town-hall-no-weight"
                    : "town-hall-record-meta"
                }
              >
                {record.meta}
              </span>
            )}
            {showMeta && bases && (
              <span className="town-hall-record-bases">
                {record.bases_meta}
              </span>
            )}
          </a>
        ))}
      </div>
    );
  }
  return (
    <nav className="town-hall-records" aria-label="Town Halls">
      {add?.endpoint && (
        <a
          className="town-hall-add primary"
          href={add.endpoint}
          onClick={(event) => follow(event, add.endpoint!)}
        >
          Add Town Hall
        </a>
      )}
      {setting && !setting.endpoint && (
        <div className="town-hall-setting">
          <span>Lowest FWA Town Hall</span>
          <strong>{setting.value}</strong>
        </div>
      )}
      {setting?.endpoint && (
        <a
          className="town-hall-setting"
          href={setting.endpoint}
          onClick={(event) => follow(event, setting.endpoint!)}
        >
          <span>Lowest FWA Town Hall</span>
          <strong>{setting.value}</strong>
        </a>
      )}
      <section aria-label="FWA levels">
        <h2>FWA levels</h2>
        <div
          className={`town-hall-column-headings ${bases ? "has-bases" : ""}`}
          aria-hidden="true"
        >
          <span>Town Hall</span>
          <span>Weight range</span>
          {bases && <span>Bases</span>}
        </div>
        {rows(fwa, true)}
      </section>
      {other.length > 0 && (
        <details className="town-hall-other">
          <summary>Other levels ({other.length})</summary>
          {rows(other, false)}
        </details>
      )}
    </nav>
  );
}
