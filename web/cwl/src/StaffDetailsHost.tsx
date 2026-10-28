import { lazy, Suspense, useLayoutEffect, useState } from "react";
import {
  staffDetailsPageEvent,
  type StaffDetailsPage,
} from "./useStaffDetailsPage";
import {
  staffDetailsEvent,
  type StaffDetailsRequest,
} from "./staffDetailsRequest";

const StaffDetailsPanel = lazy(() => import("./StaffDetailsPanel"));

/** Eager request owner; the panel and its CSS remain in the lazy chunk. */
export default function StaffDetailsHost({
  archived = false,
  initialAccount = null,
  onInitialConsumed,
}: {
  archived?: boolean;
  initialAccount?: string | null;
  onInitialConsumed?: () => void;
}) {
  const [request, setRequest] = useState<StaffDetailsRequest | null>(null);
  useLayoutEffect(() => {
    const open = (event: Event) =>
      setRequest((event as CustomEvent<StaffDetailsRequest>).detail);
    window.addEventListener(staffDetailsEvent, open);
    let consumed = false;
    const registered = (event: Event) => {
      if (!initialAccount) return;
      const page = (event as CustomEvent<StaffDetailsPage>).detail;
      if (consumed) {
        if (!page.openDirect)
          setRequest((current) => (current ? { ...current, ...page } : null));
        return;
      }
      consumed = true;
      onInitialConsumed?.();
      if (page.openDirect) page.openDirect(initialAccount);
      else setRequest({ ...page, tag: initialAccount });
    };
    window.addEventListener(staffDetailsPageEvent, registered);
    return () => {
      window.removeEventListener(staffDetailsEvent, open);
      window.removeEventListener(staffDetailsPageEvent, registered);
    };
  }, []);
  useLayoutEffect(() => {
    request?.onOpenChange?.(true);
    return () => request?.onOpenChange?.(false);
  }, [request?.onOpenChange]);
  return request ? (
    <Suspense fallback={<div role="status">Loading account details…</div>}>
      <StaffDetailsPanel
        request={request}
        setRequest={setRequest}
        archived={archived}
      />
    </Suspense>
  ) : null;
}
