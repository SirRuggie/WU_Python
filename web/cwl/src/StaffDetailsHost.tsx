import { lazy, Suspense, useLayoutEffect, useState } from "react";
import { detailsAccount } from "./detailsNavigation";
import {
  staffDetailsEvent,
  type StaffDetailsRequest,
} from "./staffDetailsRequest";

const StaffDetailsPanel = lazy(() => import("./StaffDetailsPanel"));

/** Eager request owner; the panel and its CSS remain in the lazy chunk. */
export default function StaffDetailsHost({
  archived = false,
}: {
  archived?: boolean;
}) {
  const [request, setRequest] = useState<StaffDetailsRequest | null>(null);
  useLayoutEffect(() => {
    const open = (event: Event) =>
      setRequest((event as CustomEvent<StaffDetailsRequest>).detail);
    window.addEventListener(staffDetailsEvent, open);
    const tag = detailsAccount();
    const seasonId = new URLSearchParams(location.search).get("season");
    if (tag && seasonId && location.pathname !== "/cwl/roster")
      setRequest({
        tag,
        seasonId,
        viewOnly:
          location.pathname === "/cwl/readiness" ? "declaration" : undefined,
      });
    return () => window.removeEventListener(staffDetailsEvent, open);
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
