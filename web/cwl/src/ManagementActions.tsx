import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { api } from "./api";
import type { PreviewPart } from "./DiscordMessagePreview";
import {
  actionConfirmation,
  actionNeedsConfirmation,
  fieldError,
  fieldValues,
  type ManagementDocument,
  type ManagementRequestIds,
  type ManagementResult,
  type ManagementSection,
  type ManagementValue,
} from "./serverManagement";
import {
  apiPath,
  hydrateFields,
  message,
  sectionEndpoint,
} from "./managementRequests";

type Props = {
  selected: ManagementSection;
  document: ManagementDocument;
  draft: Record<string, ManagementValue>;
  busy: boolean;
  dirty: boolean;
  statusUrl: string;
  ask: (text: string, label?: string) => Promise<boolean>;
  writing: MutableRefObject<boolean>;
  sequence: MutableRefObject<number>;
  requestIds: MutableRefObject<ManagementRequestIds>;
  pendingKeys: MutableRefObject<Map<string, string>>;
  checkAction: (url: string, wait?: boolean) => Promise<string | undefined>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string>>;
  setNotice: Dispatch<SetStateAction<string>>;
  setActionResult: Dispatch<SetStateAction<ManagementResult | null>>;
  setDraft: Dispatch<SetStateAction<Record<string, ManagementValue>>>;
  setPreview: Dispatch<SetStateAction<PreviewPart[] | null>>;
  setSelected: Dispatch<SetStateAction<ManagementSection | null>>;
  setDocument: Dispatch<SetStateAction<ManagementDocument | null>>;
  setDocuments: Dispatch<SetStateAction<ManagementSection[]>>;
};

export default function ManagementActions({
  selected,
  document,
  draft,
  busy,
  dirty,
  statusUrl,
  ask,
  writing,
  sequence,
  requestIds,
  pendingKeys,
  checkAction,
  setBusy,
  setError,
  setNotice,
  setActionResult,
  setDraft,
  setPreview,
  setSelected,
  setDocument,
  setDocuments,
}: Props) {
  return (
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
                    busy || !!statusUrl || (dirty && !document.action_only)
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
                    if (writing.current || turn !== sequence.current) return;
                    writing.current = true;
                    setBusy(true);
                    setError("");
                    setActionResult(null);
                    const actionEndpoint = apiPath(
                      action.endpoint ||
                        `${sectionEndpoint(selected)}/actions/${encodeURIComponent(action.id)}`,
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
                        pendingKeys.current.set(outcome.status_url, requestKey);
                        const status = await checkAction(
                          outcome.status_url,
                          true,
                        );
                        if (status !== "done") return;
                      } else {
                        requestIds.current.complete(requestKey);
                        setActionResult(
                          outcome.url || outcome.details || outcome.accounts
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
                        sectionEndpoint(selected),
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
              {document.id === "band_monitor" ? "Diagnostics" : "More options"}
            </summary>
            {content}
          </details>
        ) : (
          <div key="primary">{content}</div>
        );
      })}
    </div>
  );
}
