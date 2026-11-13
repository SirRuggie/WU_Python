import type { RefObject } from "react";
import LoadError from "../LoadError";

export default function StrikesNotices({
  error,
  notice,
  noticeRef,
  busy,
  showLeaveRefresh,
  showRecordsRefresh,
  onLeaveRefresh,
  onRecordsRefresh,
}: {
  error: string;
  notice: string;
  noticeRef: RefObject<HTMLDivElement | null>;
  busy: boolean;
  showLeaveRefresh: boolean;
  showRecordsRefresh: boolean;
  onLeaveRefresh: () => void;
  onRecordsRefresh: () => void;
}) {
  return (
    <>
      <LoadError
        message={error}
        disabled={busy}
        onRetry={showRecordsRefresh ? onRecordsRefresh : undefined}
      />
      {error && showLeaveRefresh && (
        <button disabled={busy} onClick={onLeaveRefresh}>
          Refresh
        </button>
      )}
      {notice && (
        <div
          className="notice success"
          role="status"
          ref={noticeRef}
          tabIndex={-1}
        >
          {notice}
        </div>
      )}
    </>
  );
}
