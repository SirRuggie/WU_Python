import { useLayoutEffect, useRef } from "react";
import type { StaffDetailsRequest } from "./staffDetailsRequest";

export const staffDetailsPageEvent = "wu:staff-details-page";
export type StaffDetailsPage = Omit<StaffDetailsRequest, "tag"> & {
  openDirect?: (tag: string) => void;
};

/** Register before the lazy page's paint; callbacks always use its current state. */
export default function useStaffDetailsPage(page: StaffDetailsPage) {
  const current = useRef(page);
  current.current = page;
  useLayoutEffect(() => {
    const registration: StaffDetailsPage = {
      seasonId: page.seasonId,
      get order() {
        return current.current.order;
      },
      get archived() {
        return current.current.archived;
      },
      get viewOnly() {
        return current.current.viewOnly;
      },
      ...(page.openDirect
        ? { openDirect: (tag: string) => current.current.openDirect?.(tag) }
        : {}),
      onChanged: () => current.current.onChanged?.(),
      onDirty: (dirty) => current.current.onDirty?.(dirty),
      onBusy: (busy) => current.current.onBusy?.(busy),
      onOpenChange: (open) => current.current.onOpenChange?.(open),
    };
    window.dispatchEvent(
      new CustomEvent(staffDetailsPageEvent, { detail: registration }),
    );
  }, [page.seasonId, JSON.stringify(page.order), page.archived]);
}
