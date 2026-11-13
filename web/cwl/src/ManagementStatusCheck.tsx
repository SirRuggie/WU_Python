import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { api } from "./api";
import type { PreviewPart } from "./DiscordMessagePreview";
import {
  fieldValues,
  type ManagementDocument,
  type ManagementSection,
  type ManagementValue,
} from "./serverManagement";
import { hydrateFields, message, sectionEndpoint } from "./managementRequests";

type Props = {
  selected: ManagementSection | null;
  statusUrl: string;
  busy: boolean;
  writing: MutableRefObject<boolean>;
  sequence: MutableRefObject<number>;
  checkAction: (url: string, wait?: boolean) => Promise<string | undefined>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string>>;
  setConflict: Dispatch<SetStateAction<boolean>>;
  setDocument: Dispatch<SetStateAction<ManagementDocument | null>>;
  setDraft: Dispatch<SetStateAction<Record<string, ManagementValue>>>;
  setPreview: Dispatch<SetStateAction<PreviewPart[] | null>>;
};

export default function ManagementStatusCheck({
  selected,
  statusUrl,
  busy,
  writing,
  sequence,
  checkAction,
  setBusy,
  setError,
  setConflict,
  setDocument,
  setDraft,
  setPreview,
}: Props) {
  return (
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
            const result = await api<ManagementDocument>(
              sectionEndpoint(current),
            );
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
  );
}
