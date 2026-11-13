import type { RefObject } from "react";

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
      {error && (
        <div className="notice error" role="alert">
          {error}
          {showLeaveRefresh && (
            <button disabled={busy} onClick={onLeaveRefresh}>
              Refresh
            </button>
          )}
          {showRecordsRefresh && (
            <button disabled={busy} onClick={onRecordsRefresh}>
              Refresh records
            </button>
          )}
        </div>
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
