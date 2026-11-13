import LoadError from "./LoadError";
import PageEyebrow from "./PageEyebrow";
import SectionTabs from "./SectionTabs";
import ServerSettingsIndex from "./ServerSettingsIndex";
import { bandStatusWarning } from "./BandStatusSummary";
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
import DiscordPreview, { type PreviewPart } from "./DiscordMessagePreview";
import useCompactPreview from "./useCompactPreview";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import {
  recordPickerCopy,
  type ManagementResult,
  ManagementRequestIds,
  changedValues,
  fieldError,
  fieldValues,
  type ManagementDocument,
  type ManagementSection,
  type ManagementValue,
} from "./serverManagement";
import {
  apiPath,
  hydrateFields,
  message,
  sectionEndpoint,
} from "./managementRequests";
import useManagementConfirmation from "./useManagementConfirmation";
import ManagementActionResult from "./ManagementActionResult";
import ManagementActions from "./ManagementActions";
import ManagementEditorForm from "./ManagementEditorForm";
import ManagementRecordNavigation from "./ManagementRecordNavigation";
import ManagementStatusCheck from "./ManagementStatusCheck";
import "./ServerManagement.css";
import "./navList.css";
type Props = {
  area?: ManagementArea;
  onNavigate?: (destination: string) => void;
  onDirty?: (dirty: boolean) => void;
};

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
  const endpoint = sectionEndpoint;
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
            {(selected?.id === directSection?.id && areaInfo?.title) ||
              selected?.label ||
              areaInfo?.title ||
              "Manage your server"}
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
      {notice && (
        <p className="manage-notice" role="status">
          {notice}
        </p>
      )}
      {actionResult && <ManagementActionResult actionResult={actionResult} />}
      {statusUrl && (
        <ManagementStatusCheck
          selected={selected}
          statusUrl={statusUrl}
          busy={busy}
          writing={writing}
          sequence={sequence}
          checkAction={checkAction}
          setBusy={setBusy}
          setError={setError}
          setConflict={setConflict}
          setDocument={setDocument}
          setDraft={setDraft}
          setPreview={setPreview}
        />
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
        <ManagementRecordNavigation
          documents={documents}
          selected={selected}
          busy={busy}
          pickerCopy={pickerCopy}
          onOpen={(record) => void open(record, true)}
        />
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
            <ManagementEditorForm
              selected={selected}
              document={document}
              draft={draft}
              busy={busy}
              dirty={dirty}
              conflict={conflict}
              publishDirty={publishDirty}
              statusUrl={statusUrl}
              fieldPage={fieldPage}
              compactPreview={compactPreview}
              operationsWorkspace={operationsWorkspace}
              onSave={(review) => void save(review)}
              setFieldPage={setFieldPage}
              setMobilePane={setMobilePane}
              setDocument={setDocument}
              setDraft={setDraft}
              setNotice={setNotice}
            />
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
          <ManagementActions
            selected={selected}
            document={document}
            draft={draft}
            busy={busy}
            dirty={dirty}
            statusUrl={statusUrl}
            ask={ask}
            writing={writing}
            sequence={sequence}
            requestIds={requestIds}
            pendingKeys={pendingKeys}
            checkAction={checkAction}
            setBusy={setBusy}
            setError={setError}
            setNotice={setNotice}
            setActionResult={setActionResult}
            setDraft={setDraft}
            setPreview={setPreview}
            setSelected={setSelected}
            setDocument={setDocument}
            setDocuments={setDocuments}
          />{" "}
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
