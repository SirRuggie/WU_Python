import { useEffect, useState } from "react";
import MemberPicker, { type MemberOption } from "./MemberPicker";
import { previewUrl } from "./previewFormatting";
import { apiUpload } from "./api";
import { apiPath, message } from "./managementRequests";
import type { ManagementField, ManagementValue } from "./serverManagement";

export default function Field({
  field,
  value,
  onChange,
  disabled,
  revision,
  onMemberOptions,
  memberRoles,
}: {
  field: ManagementField;
  value: ManagementValue;
  onChange: (value: ManagementValue) => void;
  disabled: boolean;
  revision: string | number;
  onMemberOptions?: (options: MemberOption[]) => void;
  memberRoles?: { value: string; label: string }[];
}) {
  const [search, setSearch] = useState(""),
    [uploading, setUploading] = useState(false),
    [uploadError, setUploadError] = useState("");
  const id = `manage-${field.key.replace(/[^a-z0-9]/gi, "-")}`;
  const [remoteOptions, setRemoteOptions] = useState(field.options || []);
  useEffect(() => {
    setRemoteOptions(field.options || []);
  }, [field.options]);

  const options = remoteOptions;
  const matching = options.filter((option) =>
    `${option.label} ${option.value}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const picker =
    !!field.source ||
    ["role", "channel", "member", "multiselect"].includes(field.type);
  const multiple = field.type === "multiselect" || Array.isArray(value);
  if (field.type === "member" || field.source === "members")
    return (
      <MemberPicker
        compactSelection
        label={field.label}
        value={value}
        onChange={onChange}
        disabled={disabled || !!field.readonly}
        multiple={multiple}
        onOptions={onMemberOptions}
        roles={memberRoles}
      />
    );
  return (
    <div
      className={`manage-field ${field.type === "textarea" ? "manage-field-wide" : ""}`}
    >
      {field.type === "boolean" ? (
        <label className="manage-switch" htmlFor={id}>
          <input
            id={id}
            type="checkbox"
            checked={Boolean(value)}
            disabled={disabled || field.readonly}
            onChange={(event) => onChange(event.target.checked)}
          />
          {field.label}
        </label>
      ) : (
        <>
          <label htmlFor={id}>
            {field.label}
            {field.required ? " *" : ""}
          </label>
          {picker && (
            <input
              aria-label={`Find ${field.label.toLowerCase()}`}
              placeholder="Search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              disabled={disabled || field.readonly}
            />
          )}
          {field.type === "textarea" ? (
            <textarea
              id={id}
              rows={String(field.value ?? "").length < 160 ? 3 : 5}
              value={String(value ?? "")}
              disabled={disabled || field.readonly}
              maxLength={field.max_length}
              aria-describedby={field.description ? `${id}-help` : undefined}
              onChange={(event) => onChange(event.target.value)}
            />
          ) : multiple ? (
            <div
              id={id}
              className="manage-option-checks"
              role="group"
              aria-label={field.label}
            >
              {matching.length ? (
                matching.map((option) => (
                  <label key={option.value}>
                    <input
                      type="checkbox"
                      disabled={disabled || field.readonly}
                      checked={
                        Array.isArray(value) && value.includes(option.value)
                      }
                      onChange={(event) =>
                        onChange(
                          event.target.checked
                            ? [
                                ...(Array.isArray(value) ? value : []),
                                option.value,
                              ]
                            : (Array.isArray(value) ? value : []).filter(
                                (item) => item !== option.value,
                              ),
                        )
                      }
                    />
                    {option.label}
                  </label>
                ))
              ) : (
                <small>No matches found.</small>
              )}
            </div>
          ) : picker || field.type === "select" ? (
            <select
              id={id}
              multiple={multiple}
              size={
                multiple ? Math.min(6, Math.max(3, matching.length)) : undefined
              }
              disabled={disabled || field.readonly}
              value={
                multiple
                  ? Array.isArray(value)
                    ? value
                    : []
                  : String(value ?? "")
              }
              onChange={(event) =>
                onChange(
                  multiple
                    ? Array.from(
                        event.target.selectedOptions,
                        (option) => option.value,
                      )
                    : event.target.value,
                )
              }
            >
              {!multiple && (
                <option value="">Select {field.label.toLowerCase()}</option>
              )}
              {options
                .filter(
                  (option) =>
                    matching.includes(option) ||
                    (Array.isArray(value)
                      ? value.includes(option.value)
                      : option.value === String(value)),
                )
                .map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              {!multiple &&
                value &&
                !options.some((option) => option.value === String(value)) && (
                  <option value={String(value)}>
                    Current selection · {String(value)}
                  </option>
                )}
            </select>
          ) : (
            <input
              id={id}
              type={field.type === "number" ? "number" : "text"}
              value={String(value ?? "")}
              disabled={disabled || field.readonly}
              min={field.min}
              max={field.max}
              maxLength={field.max_length}
              placeholder={field.placeholder}
              onChange={(event) =>
                onChange(
                  field.type === "number" && event.target.value !== ""
                    ? Number(event.target.value)
                    : event.target.value,
                )
              }
            />
          )}
        </>
      )}
      {field.upload_endpoint && previewUrl(String(value || "")) && (
        <div className="manage-image-current">
          <small>Current {field.label.toLowerCase()}</small>
          <img
            src={previewUrl(String(value))}
            alt={field.label}
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        </div>
      )}
      {field.upload_endpoint && (
        <label className="manage-upload">
          {uploading
            ? "Uploading image…"
            : field.upload_label || `Upload ${field.label.toLowerCase()}`}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            disabled={disabled || uploading}
            onChange={async (event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              setUploadError("");
              if (file.size > (field.upload_max_bytes || 10 * 1024 * 1024)) {
                setUploadError(
                  "This image is too large. Select a smaller image.",
                );
                return;
              }
              setUploading(true);
              try {
                const result = await apiUpload<{ url: string }>(
                  apiPath(field.upload_endpoint!) +
                    `?revision=${encodeURIComponent(revision)}`,
                  file,
                );
                onChange(result.url);
              } catch (error) {
                setUploadError(message(error));
              } finally {
                setUploading(false);
              }
            }}
          />
        </label>
      )}
      {uploadError && <p role="alert">{uploadError}</p>}
      {field.description && (
        <small id={`${id}-help`}>{field.description}</small>
      )}
    </div>
  );
}
