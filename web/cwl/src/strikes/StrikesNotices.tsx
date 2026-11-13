import type { RefObject } from "react";
import LoadError from "../LoadError";

export default function StrikesNotices({
  error,
  notice,
  noticeRef,
  busy,
  showLeaveRefresh,
  onLeaveRefresh,
  onRetry,
}: {
  error: string;
  notice: string;
  noticeRef: RefObject<HTMLDivElement | null>;
  busy: boolean;
  showLeaveRefresh: boolean;
  onLeaveRefresh: () => void;
  onRetry?: () => void;
}) {
  return (
    <>
      <LoadError message={error} disabled={busy} onRetry={onRetry} />
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
