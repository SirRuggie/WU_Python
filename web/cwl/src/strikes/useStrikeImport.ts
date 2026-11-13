import { useEffect, useState, type MutableRefObject } from "react";
import { api, ApiError } from "../api";
import {
  isStrikeImportJob,
  StrikeImportFailed,
  waitForStrikeImport,
  type StrikeImportJob,
} from "../strikeImportJobs";
import { errorText, importResultText, importStorageKey } from "./format";
import type {
  ActiveImportJob,
  ImportDraft,
  ImportPreview,
  ImportResult,
} from "./types";

export default function useStrikeImport({
  userId,
  initial,
  mutation,
  setBusy,
  setError,
  setNotice,
  refreshHistory,
}: {
  userId: string;
  initial: ImportDraft;
  mutation: MutableRefObject<boolean>;
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
  setNotice: (notice: string) => void;
  refreshHistory: () => Promise<void>;
}) {
  const [preview, setPreview] = useState<ImportPreview | null>(initial.preview);
  const [excluded, setExcluded] = useState<string[]>(initial.excluded);
  const [importJob, setImportJob] = useState<ActiveImportJob | null>(
    initial.job,
  );
  const [jobRetryPaused, setJobRetryPaused] = useState(false);
  const [jobRetry, setJobRetry] = useState(0);
  useEffect(() => {
    try {
      if (!preview && !importJob)
        sessionStorage.removeItem(importStorageKey(userId));
      else
        sessionStorage.setItem(
          importStorageKey(userId),
          JSON.stringify({ preview, excluded, job: importJob }),
        );
    } catch {
      /* Browser storage is optional; active page still works. */
    }
  }, [userId, preview, excluded, importJob]);
  useEffect(() => {
    if (!importJob || jobRetryPaused) return;
    const controller = new AbortController();
    void waitForStrikeImport<ImportPreview | ImportResult>(
      importJob.job_id,
      (id) =>
        api<StrikeImportJob<ImportPreview | ImportResult>>(
          `/strikes/import/jobs/${encodeURIComponent(id)}`,
        ),
      controller.signal,
    )
      .then((result) => {
        if (controller.signal.aborted) return;
        if (importJob.phase === "preview") {
          setPreview(result as ImportPreview);
          setExcluded([]);
          setNotice("Preview ready.");
        } else {
          setPreview(null);
          setExcluded([]);
          setNotice(importResultText(result as ImportResult));
          void refreshHistory();
        }
        setImportJob(null);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (
          err instanceof StrikeImportFailed ||
          (err instanceof ApiError && err.status === 404)
        )
          setImportJob(null);
        else setJobRetryPaused(true);
        setError(errorText(err));
      });
    return () => controller.abort();
  }, [
    importJob?.job_id,
    importJob?.phase,
    refreshHistory,
    jobRetry,
    jobRetryPaused,
  ]);
  const startImportPreview = async () => {
    if (mutation.current) return;
    mutation.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<ImportPreview | StrikeImportJob<ImportPreview>>(
        "/strikes/import/preview",
        "POST",
        { days: 60 },
      );
      if (isStrikeImportJob(result)) {
        setJobRetryPaused(false);
        setImportJob({ job_id: result.job_id, phase: "preview" });
      } else {
        setPreview(result as ImportPreview);
        setExcluded([]);
        setNotice("Preview ready.");
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  };
  const startImportApply = async () => {
    if (!preview || mutation.current) return;
    mutation.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<ImportResult | StrikeImportJob<ImportResult>>(
        "/strikes/import/apply",
        "POST",
        { preview_id: preview.preview_id, excluded_keys: excluded },
      );
      if (isStrikeImportJob(result)) {
        setJobRetryPaused(false);
        setImportJob({ job_id: result.job_id, phase: "apply" });
      } else {
        setPreview(null);
        setExcluded([]);
        setNotice(importResultText(result as ImportResult));
        void refreshHistory();
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  };
  const retryStatus = () => {
    setJobRetryPaused(false);
    setError("");
    setJobRetry((value) => value + 1);
  };
  return {
    preview,
    setPreview,
    excluded,
    setExcluded,
    importJob,
    setImportJob,
    jobRetryPaused,
    startImportPreview,
    startImportApply,
    retryStatus,
  };
}
