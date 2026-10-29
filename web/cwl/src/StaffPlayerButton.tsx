import type { ReactNode } from "react";
import { requestDetailsNavigation } from "./detailsNavigation";
import {
  staffDetailsEvent,
  type StaffDetailsRequest,
} from "./staffDetailsRequest";
export default function StaffPlayerButton({
  children,
  disabled = false,
  rosterUi: _rosterUi,
  ...request
}: StaffDetailsRequest & {
  children: ReactNode;
  disabled?: boolean;
  rosterUi?: boolean;
}) {
  return (
    <button
      type="button"
      className="roster-player-name"
      disabled={disabled}
      title="Account details"
      onClick={(event) => {
        const trigger = event.currentTarget;
        requestDetailsNavigation(() =>
          window.dispatchEvent(
            new CustomEvent(staffDetailsEvent, {
              detail: { ...request, trigger },
            }),
          ),
        );
      }}
    >
      {children}
    </button>
  );
}
