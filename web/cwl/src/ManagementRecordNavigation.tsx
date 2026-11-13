import SearchPicker from "./SearchPicker";
import type { ManagementSection } from "./serverManagement";

export default function ManagementRecordNavigation({
  documents,
  selected,
  busy,
  pickerCopy,
  onOpen,
}: {
  documents: ManagementSection[];
  selected: ManagementSection;
  busy: boolean;
  pickerCopy: { label: string; placeholder: string };
  onOpen: (section: ManagementSection) => void;
}) {
  return (
    <section className="manage-record-navigation" aria-label={pickerCopy.label}>
      {documents.length <= 8 ? (
        <div className="manage-section-choices nav-list">
          {documents.map((record) => (
            <button
              key={record.id}
              disabled={busy}
              aria-pressed={record.id === selected.id}
              onClick={() => onOpen(record)}
            >
              <span>{record.label}</span>
              <span aria-hidden="true">→</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="manage-record-picker">
          <SearchPicker
            label={pickerCopy.label}
            value={
              documents.some((item) => item.id === selected.id)
                ? selected.id
                : ""
            }
            options={documents.map((record) => ({
              value: record.id,
              label: record.label,
            }))}
            search={(query) =>
              documents
                .filter((record) =>
                  query
                    .toLowerCase()
                    .split(/\s+/)
                    .filter(Boolean)
                    .every((word) =>
                      `${record.label} ${record.id}`
                        .toLowerCase()
                        .includes(word),
                    ),
                )
                .map((record) => ({
                  value: record.id,
                  label: record.label,
                }))
            }
            disabled={busy}
            placeholder={`Select ${pickerCopy.label.toLowerCase()}`}
            searchPlaceholder={pickerCopy.placeholder}
            emptyText="No settings match."
            limit={100}
            onChange={(id) => {
              const record = documents.find((item) => item.id === id);
              if (record) onOpen(record);
            }}
          />
        </div>
      )}
    </section>
  );
}
