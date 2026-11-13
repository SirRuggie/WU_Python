import LoadError from "./LoadError";
import PageEyebrow from "./PageEyebrow";
import useConfirmDialog from "./useConfirmDialog";
import {
  registerActionPanel,
  isTopActionPanel,
  panelHistoryState,
  installPanelBackHandler,
  backOutOfPanelEntry,
} from "./actionPanelHistory";
import { countLabel } from "./countLabel";
import SectionTabs from "./SectionTabs";
import SearchPicker from "./SearchPicker";
import ServerSettingsIndex from "./ServerSettingsIndex";
import BandStatusSummary, { bandStatusWarning } from "./BandStatusSummary";
import ApplicationSettingsIndex from "./ApplicationSettingsIndex";
import ReturnReminderOverview, {
  ReturnStatusSummary,
} from "./ReturnReminderOverview";
import ChangeHistory, { supportsHistory } from "./ChangeHistory";
import MessagePublish from "./MessagePublish";
import {
  areaSections,
  managementAreas,
  type ManagementArea,
} from "./managementAreas";
import MemberPicker, { type MemberOption } from "./MemberPicker";
import { previewUrl } from "./previewFormatting";
import DiscordPreview, { type PreviewPart } from "./DiscordMessagePreview";
import useCompactPreview from "./useCompactPreview";
import { useEffect, useRef, useState } from "react";
import { api, apiUpload, ApiError } from "./api";
import {
  recordPickerCopy,
  actionConfirmation,
  actionNeedsConfirmation,
  safeDiscordUrl,
  type ManagementResult,
  ManagementRequestIds,
  changedValues,
  fieldError,
  fieldValues,
  type ManagementDocument,
  type ManagementField,
  type ManagementSection,
  type ManagementValue,
} from "./serverManagement";
import "./ServerManagement.css";
import "./navList.css";
const apiPath = (path: string) => path.replace(/^\/api\/cwl(?=\/)/, "");
const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Could not load settings. Try again.";
type Props = {
  area?: ManagementArea;
  onNavigate?: (destination: string) => void;
  onDirty?: (dirty: boolean) => void;
};
function Field({
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
async function hydrateFields(fields: ManagementField[]) {
  if (
    !fields.some(
      (field) =>
        (field.source === "roles" ||
          field.source === "channels" ||
          ["channel", "role", "multiselect"].includes(field.type)) &&
        !field.options &&
        field.source !== "members",
    )
  )
    return fields;
  const choices = await api<{
    channels: { value: string; label: string }[];
    roles: { value: string; label: string }[];
  }>("/manage/choices");
  return fields.map((field) =>
    field.options
      ? field
      : {
          ...field,
          options:
            field.source === "members"
              ? []
              : field.type === "channel" || field.source === "channels"
                ? choices.channels
                : field.source === "roles" ||
                    ["role", "multiselect"].includes(field.type)
                  ? choices.roles
                  : undefined,
        },
  );
}

let managementConfirmationSerial = 0;
function useManagementConfirmation() {
  const [decision, setDecision] = useState(0);
  const pending = useRef(false);
  const { confirm, dialog } = useConfirmDialog(String(decision));
  async function ask(text: string, label = "Discard changes") {
    if (pending.current) return false;
    pending.current = true;
    const marker = `management-confirm-${++managementConfirmationSerial}`;
    const unregister = registerActionPanel(marker);
    const state = panelHistoryState(window.history.state, marker);
    let consumed = false;
    window.history.pushState(state, "", window.location.href);
    const uninstall = installPanelBackHandler({
      windowPort: window,
      historyPort: window.history,
      marker,
      panelState: state,
      isBusy: () => false,
      isTop: () => isTopActionPanel(marker),
      close: () => {
        consumed = true;
        setDecision((value) => value + 1);
      },
    });
    try {
      return await confirm(text, label);
    } finally {
      uninstall();
      unregister();
      if (!consumed)
        backOutOfPanelEntry({
          windowPort: window,
          historyPort: window.history,
          marker,
        });
      pending.current = false;
    }
  }
  return { ask, dialog };
}

export default function ServerManagement({ onNavigate, onDirty, area }: Props) {
  const [sections, setSections] = useState<ManagementSection[]>([]),
    [query, setQuery] = useState(""),
    [documents, setDocuments] = useState<ManagementSection[]>([]),
    [selected, setSelected] = useState<ManagementSection | null>(null),
    [document, setDocument] = useState<ManagementDocument | null>(null),
    [draft, setDraft] = useState<Record<string, ManagementValue>>({}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [preview, setPreview] = useState<PreviewPart[] | null>(null),
    [conflict, setConflict] = useState(false),
    [fieldPage, setFieldPage] = useState(0),
    [statusUrl, setStatusUrl] = useState(""),
    [actionResult, setActionResult] = useState<ManagementResult | null>(null);
  const pickerCopy = recordPickerCopy(documents);
  const [previewStatus, setPreviewStatus] = useState(""),
    [mobilePane, setMobilePane] = useState<"edit" | "preview">("edit");
  const compactPreview = useCompactPreview(900);
  const operationsWorkspace =
    !area || area === "fwa-settings" || area === "connections-settings";

  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [returnDirty, setReturnDirty] = useState(false);
  const [publishDirty, setPublishDirty] = useState(false);
  const writing = useRef(false),
    indexTrigger = useRef<HTMLButtonElement | null>(null),
    editorHeading = useRef<HTMLHeadingElement | null>(null);
  const sequence = useRef(0),
    requestIds = useRef(new ManagementRequestIds()),
    pendingKeys = useRef(new Map<string, string>()),
    explicitPreviewKey = useRef<string | null>(null);
  const changes = document ? changedValues(document.fields, draft) : {};
  const dirty = Object.keys(changes).length > 0;
  const draftPreviewKey = JSON.stringify(changes);
  const previewKey =
    selected && document
      ? `${selected.id}:${document.revision}:${draftPreviewKey}`
      : "";
  const previewVisible =
    (!operationsWorkspace && !compactPreview) || mobilePane === "preview";
  useEffect(() => {
    onDirty?.(
      dirty ||
        returnDirty ||
        publishDirty ||
        (busy && writing.current) ||
        !!statusUrl,
    );
    return () => onDirty?.(false);
  }, [dirty, returnDirty, publishDirty, busy, statusUrl, onDirty]);
  useEffect(() => {
    if (
      !dirty &&
      !returnDirty &&
      !publishDirty &&
      !writing.current &&
      !statusUrl
    )
      return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, returnDirty, publishDirty, busy, statusUrl]);
  useEffect(() => {
    if (area === "cwl-returns") return;
    let alive = true;
    setBusy(true);
    setError("");
    api<{ sections: ManagementSection[] }>("/manage")
      .then((result) => {
        if (alive) setSections(result.sections);
      })
      .catch((error) => {
        if (alive) setError(message(error));
      })
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [catalogAttempt, area]);
  const endpoint = (section: ManagementSection) =>
    apiPath(section.endpoint || `/manage/${encodeURIComponent(section.id)}`);
  useEffect(() => {
    if (!selected || !document?.preview_supported || !previewVisible || busy)
      return;
    let alive = true;
    if (!dirty) {
      setPreview(document.preview || []);
      setPreviewStatus("");
      return;
    }
    if (explicitPreviewKey.current === previewKey) return;
    setPreviewStatus("Updating preview…");
    const timer = window.setTimeout(() => {
      api<ManagementDocument>(endpoint(selected) + "/preview", "POST", {
        revision: document.revision,
        values: JSON.parse(draftPreviewKey),
      })
        .then((result) => {
          if (alive) {
            setPreview(result.preview || []);
            setPreviewStatus("Draft preview · not saved");
          }
        })
        .catch((error) => {
          if (alive)
            setPreviewStatus(
              "Showing the last valid preview. " + message(error),
            );
        });
    }, 700);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [
    selected?.id,
    document?.revision,
    document?.preview_supported,
    draftPreviewKey,
    dirty,
    previewVisible,
    busy,
    previewKey,
  ]);
  const { ask, dialog } = useManagementConfirmation();
  const leaving = useRef(false);
  const mayLeave = async () => {
    if (writing.current || statusUrl || leaving.current) return false;
    leaving.current = true;
    const turn = sequence.current;
    try {
      const allowed =
        !(dirty || publishDirty) ||
        (await ask(
          "You have changes that are not saved. Leave without saving?",
        ));
      return allowed && !writing.current && turn === sequence.current;
    } finally {
      leaving.current = false;
    }
  };
  const open = async (section: ManagementSection, keepDocuments = false) => {
    if (!(await mayLeave())) return;
    if (section.destination) {
      onNavigate?.(section.destination);
      return;
    }
    const turn = ++sequence.current;
    setFieldPage(0);
    setMobilePane("edit");
    setPreviewStatus("");
    explicitPreviewKey.current = null;
    setSelected(section);
    window.requestAnimationFrame(() => editorHeading.current?.focus());
    setActionResult(null);
    if (!keepDocuments) {
      setDocuments([]);
    }
    setDocument(null);
    setDraft({});
    setPreview(null);
    setError("");
    setNotice("");
    setConflict(false);
    setBusy(true);
    try {
      const result = await api<ManagementDocument>(endpoint(section));
      if (turn === sequence.current) {
        if (result.documents) {
          setDocuments(
            result.documents.map((record) => ({ ...section, ...record })),
          );
          setDocument(null);
        } else {
          const fields = await hydrateFields(result.fields || []);
          if (turn !== sequence.current) return;
          setDocument({ ...result, fields });
          setDraft(fieldValues(fields));
          setPreview(result.preview || null);
        }
      }
    } catch (error) {
      if (turn === sequence.current) setError(message(error));
    } finally {
      if (turn === sequence.current) setBusy(false);
    }
  };
  const home = async () => {
    if (!(await mayLeave())) return;
    ++sequence.current;
    setSelected(null);
    setActionResult(null);
    setDocuments([]);
    setDocument(null);
    setDraft({});
    setError("");
    setNotice("");
    setBusy(false);
    window.requestAnimationFrame(() => indexTrigger.current?.focus());
  };
  // Band monitor holds one section: open it directly (D7). Once per visit,
  // so a failed load shows its error instead of retrying in a loop.
  const areaList = area ? areaSections(sections, area) : sections;
  const directSection =
    area === "connections-settings" && areaList.length === 1
      ? areaList[0]
      : null;
  const autoOpened = useRef(false);
  useEffect(() => {
    if (!directSection || selected || busy || error || autoOpened.current)
      return;
    autoOpened.current = true;
    void open(directSection);
  });
  const checkAction = async (url: string, wait = false) => {
    for (let attempt = 0; attempt < (wait ? 30 : 1); attempt++) {
      const result = await api<{
        status: string;
        message?: string;
        result?: ManagementResult;
      }>(apiPath(url));
      setNotice(result.message || `Request ${result.status}.`);
      if (["done", "failed", "uncertain"].includes(result.status)) {
        if (result.status === "done") {
          setActionResult(result.result || null);
          const key = pendingKeys.current.get(url);
          if (key) requestIds.current.complete(key);
          pendingKeys.current.delete(url);
        }
        setStatusUrl("");
        if (result.status !== "done")
          setError(
            result.message ||
              "The request could not be confirmed. Check Discord before trying again.",
          );
        return result.status;
      }
      setStatusUrl(url);
      if (wait)
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    setNotice(
      "Still waiting for the bot. Use Check request status to see the result. Do not send the same request again.",
    );
  };
  const save = async (review = false) => {
    if (writing.current || !selected || !document) return;
    const invalid = document.fields
      .map((field) => fieldError(field, draft[field.key]))
      .find(Boolean);
    if (invalid) {
      setError(invalid);
      return;
    }
    if (review) explicitPreviewKey.current = previewKey;
    writing.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const requestKey = requestIds.current.key(
      endpoint(selected),
      document.revision,
      changes,
    );
    try {
      let result = await api<
        ManagementDocument & {
          status?: string;
          status_url?: string;
          message?: string;
        }
      >(
        endpoint(selected) + (review ? "/preview" : ""),
        review ? "POST" : "PATCH",
        {
          revision: document.revision,
          values: changes,
          ...(review ? {} : { request_id: requestIds.current.get(requestKey) }),
        },
      );
      if (result.status_url) {
        pendingKeys.current.set(result.status_url, requestKey);
        setNotice(result.message || "Waiting for the bot…");
        const status = await checkAction(result.status_url, true);
        if (status !== "done") return;
        result = await api<ManagementDocument>(endpoint(selected));
      }
      if (review) {
        setPreview(result.preview || []);
        setNotice("Preview only. Nothing has been sent.");
      } else {
        requestIds.current.complete(requestKey);
        setDocument({
          ...result,
          fields: await hydrateFields(result.fields || []),
        });
        setDraft(fieldValues(result.fields || []));
        setConflict(false);
        setPreview(result.preview || null);
        setNotice("Saved.");
      }
    } catch (error) {
      setConflict(error instanceof ApiError && error.status === 409);
      setError(
        error instanceof ApiError && error.status === 409
          ? "Someone changed these settings. Your edits are still here. Keep a copy of your edits before refreshing."
          : message(error),
      );
    } finally {
      writing.current = false;
      setBusy(false);
    }
  };
  const areaInfo = area ? managementAreas[area] : null;
  return (
    <section
      className={`server-management ${area === "applications-settings" ? "applications-workspace" : ""} ${operationsWorkspace ? "server-operations-workspace" : ""}`}
    >
      {dialog}
      <header className="manage-heading">
        <div>
          <PageEyebrow />
          <h1 ref={editorHeading} tabIndex={-1}>
            {selected?.label || areaInfo?.title || "Manage your server"}
          </h1>
          <p>
            {document?.description ||
              selected?.description ||
              areaInfo?.description ||
              "Bot settings for this server."}
          </p>
        </div>
        {selected && (
          <div className="manage-categories">
            {selected.id !== directSection?.id && (
              <button disabled={busy || !!statusUrl} onClick={home}>
                ← {areaInfo?.title || "All settings"}
              </button>
            )}
            <button
              disabled={busy || !!statusUrl}
              onClick={() => void open(selected, true)}
            >
              Refresh
            </button>
          </div>
        )}
      </header>
      <LoadError
        message={error}
        disabled={busy || !!statusUrl}
        onRetry={() =>
          selected
            ? void open(selected)
            : setCatalogAttempt((value) => value + 1)
        }
        retryLabel={
          conflict
            ? "Discard edits and load latest"
            : document
              ? "Refresh saved settings"
              : "Try again"
        }
      />
      {notice && (
        <p className="manage-notice" role="status">
          {notice}
        </p>
      )}
      {actionResult && (
        <section className="manage-result" aria-label="Action result">
          <h3>Result</h3>
          {actionResult.message && <p>{actionResult.message}</p>}
          {actionResult.details && (
            <p className="manage-result-details">{actionResult.details}</p>
          )}
          {safeDiscordUrl(actionResult.url) && (
            <a
              className="target-44"
              href={safeDiscordUrl(actionResult.url)!}
              target="_blank"
              rel="noopener noreferrer"
            >
              View in Discord ↗
            </a>
          )}
          {actionResult.accounts && (
            <>
              <p>{countLabel(actionResult.accounts.length, "account")}</p>
              <ul>
                {actionResult.accounts.map((account, index) => (
                  <li key={`${account.tag || account.player_tag || index}`}>
                    <strong>
                      {account.name || account.player_name || "Account"}
                    </strong>
                    <span>{account.tag || account.player_tag}</span>
                    <small>
                      {account.current_clan_name ||
                        account.clan_name ||
                        (typeof account.current_clan === "string"
                          ? account.current_clan
                          : account.current_clan?.name) ||
                        account.clan?.name ||
                        "No current clan"}
                    </small>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
      {statusUrl && (
        <button
          disabled={busy}
          onClick={async () => {
            if (writing.current || !selected) return;
            const turn = sequence.current;
            const current = selected;
            writing.current = true;
            setBusy(true);
            try {
              const status = await checkAction(statusUrl);
              if (status === "done" && turn === sequence.current) {
                const result = await api<ManagementDocument>(endpoint(current));
                const fields = await hydrateFields(result.fields || []);
                if (turn !== sequence.current) return;
                setDocument({ ...result, fields });
                setDraft(fieldValues(fields));
                setError("");
                setConflict(false);
                setPreview(result.preview || null);
              }
            } catch (error) {
              if (turn === sequence.current) setError(message(error));
            } finally {
              writing.current = false;
              if (turn === sequence.current) setBusy(false);
            }
          }}
        >
          Check request status
        </button>
      )}
      {area === "cwl-returns" && (
        <div hidden={!!selected}>
          <ReturnReminderOverview
            active={!selected}
            onDirty={setReturnDirty}
            onOpen={(section) => void open(section)}
          />
        </div>
      )}
      {area === "applications-settings" && (
        <div hidden={!!selected || busy || !!error}>
          <ApplicationSettingsIndex
            sections={sections}
            query={query}
            onQuery={setQuery}
            onOpen={(section, trigger) => {
              indexTrigger.current = trigger;
              void open(section);
            }}
          />
        </div>
      )}
      {!selected && area === "applications-settings" && busy && (
        <p role="status">Loading application settings…</p>
      )}
      {operationsWorkspace && (
        <div hidden={!!selected || busy || !!error}>
          <ServerSettingsIndex
            sections={area ? areaSections(sections, area) : sections}
            query={query}
            onQuery={setQuery}
            onOpen={(section, trigger) => {
              indexTrigger.current = trigger;
              void open(section);
            }}
          />
        </div>
      )}
      {!selected && operationsWorkspace && busy && (
        <p role="status">Loading settings…</p>
      )}
      {selected && documents.length > 0 && (
        <section
          className="manage-record-navigation"
          aria-label={pickerCopy.label}
        >
          {documents.length <= 8 ? (
            <div className="manage-section-choices nav-list">
              {documents.map((record) => (
                <button
                  key={record.id}
                  disabled={busy}
                  aria-pressed={record.id === selected.id}
                  onClick={() => void open(record, true)}
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
                  if (record) void open(record, true);
                }}
              />
            </div>
          )}
        </section>
      )}
      {selected && busy && !document && (
        <p role="status">Loading {selected.label.toLowerCase()}…</p>
      )}
      {selected && document && (
        <>
          {document.return_status && (
            <ReturnStatusSummary status={document.return_status} />
          )}
          {document.warning && (
            <p className="manage-notice">
              {document.id === "band_monitor"
                ? bandStatusWarning(document.warning)
                : document.warning}
            </p>
          )}
          {document.preview_supported && (
            <SectionTabs
              className="manage-preview-toggle section-tabs--flow"
              label="Message editor view"
              items={[
                { id: "edit", label: <>Edit message</> },
                { id: "preview", label: <>Preview message</> },
              ]}
              value={mobilePane}
              onChange={(next) => {
                switch (next) {
                  case "edit":
                    {
                      setMobilePane("edit");
                    }
                    break;
                  case "preview":
                    {
                      setMobilePane("preview");
                    }
                    break;
                }
              }}
              revealSelection
            />
          )}
          <div
            className={
              document.preview_supported
                ? `manage-editor-layout mobile-${mobilePane}`
                : ""
            }
          >
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void save();
              }}
            >
              {document.readonly && operationsWorkspace ? (
                <BandStatusSummary fields={document.fields} />
              ) : (
                <fieldset disabled={busy || document.readonly} aria-busy={busy}>
                  <legend className="manage-sr-only">
                    {selected.label} settings
                  </legend>
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
                    ).map((field) => (
                      <Field
                        key={field.key + ":" + (document.member_refresh || "")}
                        memberRoles={
                          document.fields.find(
                            (item) => item.key === "role_ids",
                          )?.options
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
                                              [
                                                ...(item.options || []),
                                                ...options,
                                              ].map((option) => [
                                                option.value,
                                                option,
                                              ]),
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
                            void save(true);
                          }}
                        >
                          Preview
                        </button>
                      )}
                    <button
                      className="primary"
                      type="submit"
                      disabled={
                        busy ||
                        !dirty ||
                        publishDirty ||
                        conflict ||
                        !!statusUrl
                      }
                    >
                      Save changes
                    </button>
                  </div>
                </div>
              )}
            </form>
            {document.preview_supported && previewVisible && (
              <DiscordPreview parts={preview || []} status={previewStatus} />
            )}
          </div>
          {publishDirty && (
            <p className="manage-notice">
              Save or cancel the posting channel change before saving the
              message.
            </p>
          )}
          {document.publish_endpoint && (
            <MessagePublish
              onDirty={setPublishDirty}
              key={document.id + ":" + document.revision}
              endpoint={document.publish_endpoint}
              dirty={dirty}
              busy={busy}
              onBusy={(value) => {
                writing.current = value;
                setBusy(value);
              }}
            />
          )}
          <div>
            {[false, true].map((advanced) => {
              const actions = (document.actions || []).filter(
                (action) => !!action.advanced === advanced,
              );
              if (!actions.length) return null;
              const content = (
                <div>
                  {actions.map((action) => (
                    <div className="manage-action" key={action.id}>
                      <>{action.description && <p>{action.description}</p>}</>
                      <button
                        disabled={
                          busy ||
                          !!statusUrl ||
                          (dirty && !document.action_only)
                        }
                        onClick={async () => {
                          if (writing.current) return;
                          const invalid = document.fields
                            .map((field) => fieldError(field, draft[field.key]))
                            .find(Boolean);
                          if (invalid) {
                            setError(invalid);
                            return;
                          }
                          const turn = sequence.current;
                          if (
                            actionNeedsConfirmation(document.id, action.id) &&
                            !(await ask(
                              actionConfirmation(
                                action.confirm ||
                                  `${action.label}? This changes the shared server settings.`,
                                document.fields,
                                draft,
                              ),
                              action.label,
                            ))
                          )
                            return;
                          if (writing.current || turn !== sequence.current)
                            return;
                          writing.current = true;
                          setBusy(true);
                          setError("");
                          setActionResult(null);
                          const actionEndpoint = apiPath(
                            action.endpoint ||
                              `${endpoint(selected)}/actions/${encodeURIComponent(action.id)}`,
                          );
                          const requestKey = requestIds.current.key(
                            actionEndpoint,
                            document.revision,
                            draft,
                          );
                          try {
                            const outcome = await api<{
                              message?: string;
                              url?: string;
                              details?: string;
                              accounts?: ManagementResult["accounts"];
                              draft_values?: Record<string, ManagementValue>;
                              status?: string;
                              status_url?: string;
                              removed?: boolean;
                              return_endpoint?: string;
                              return_label?: string;
                            }>(actionEndpoint, "POST", {
                              revision: document.revision,
                              values: draft,
                              request_id: requestIds.current.get(requestKey),
                            });
                            setNotice(outcome.message || "Change saved.");
                            if (outcome.status_url) {
                              pendingKeys.current.set(
                                outcome.status_url,
                                requestKey,
                              );
                              const status = await checkAction(
                                outcome.status_url,
                                true,
                              );
                              if (status !== "done") return;
                            } else {
                              requestIds.current.complete(requestKey);
                              setActionResult(
                                outcome.url ||
                                  outcome.details ||
                                  outcome.accounts
                                  ? outcome
                                  : null,
                              );
                            }
                            if (outcome.draft_values) {
                              setDraft((current) => ({
                                ...current,
                                ...outcome.draft_values,
                              }));
                              setPreview(null);
                              return;
                            }
                            if (outcome.removed && outcome.return_endpoint) {
                              const next = {
                                ...selected,
                                endpoint: outcome.return_endpoint,
                                label: outcome.return_label || selected.label,
                              };
                              const root = await api<ManagementDocument>(
                                apiPath(outcome.return_endpoint),
                              );
                              setSelected(next);
                              setDocument(null);
                              setDraft({});
                              setDocuments(
                                (root.documents || []).map((record) => ({
                                  ...next,
                                  ...record,
                                })),
                              );
                              return;
                            }
                            setDraft(fieldValues(document.fields));
                            const result = await api<ManagementDocument>(
                              endpoint(selected),
                            );
                            setDocument({
                              ...result,
                              member_refresh: Date.now(),
                              fields: await hydrateFields(result.fields || []),
                            });
                            setDraft(fieldValues(result.fields || []));
                          } catch (error) {
                            setError(message(error));
                          } finally {
                            writing.current = false;
                            setBusy(false);
                          }
                        }}
                      >
                        {action.label}
                      </button>
                    </div>
                  ))}
                </div>
              );
              return advanced ? (
                <details className="manage-more-options" key="more">
                  <summary>
                    {document.id === "band_monitor"
                      ? "Diagnostics"
                      : "More options"}
                  </summary>
                  {content}
                </details>
              ) : (
                <div key="primary">{content}</div>
              );
            })}
          </div>{" "}
          {supportsHistory(endpoint(selected)) && !document.action_only && (
            <ChangeHistory
              onBusy={(value) => {
                writing.current = value;
                setBusy(value);
              }}
              key={endpoint(selected)}
              target={endpoint(selected)}
              revision={document.revision}
              labels={Object.fromEntries(
                document.fields.map((field) => [field.key, field.label]),
              )}
              disabled={busy || dirty || !!statusUrl}
              onRestored={async () => {
                const result = await api<ManagementDocument>(
                  endpoint(selected),
                );
                setDocument({
                  ...result,
                  fields: await hydrateFields(result.fields || []),
                });
                setDraft(fieldValues(result.fields || []));
                setPreview(result.preview || null);
                setConflict(false);
              }}
            />
          )}{" "}
        </>
      )}
    </section>
  );
}
