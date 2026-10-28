import type { RosterSnapshot } from "./roster";
export type StaffDetailsRequest = {
  seasonId: string;
  tag: string;
  order?: string[];
  archived?: boolean;
  viewOnly?: "declaration";
  publishedSnapshot?: {
    roster: RosterSnapshot;
    version: number;
    signupTags: string[];
  };
  trigger?: HTMLElement;
  onChanged?: () => void | Promise<unknown>;
  onDirty?: (dirty: boolean) => void;
  onBusy?: (busy: boolean) => void;
  onOpenChange?: (open: boolean) => void;
};
export const staffDetailsEvent = "wu:staff-details";
