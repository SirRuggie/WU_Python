import { useState } from "react";
import ActionPanel from "./ActionPanel";
import RosterSignupActions, { type SignupAction } from "./RosterSignupActions";
import type { RosterAccount, RosterClan } from "./roster";
import { StatusPill } from "./rosterUi/primitives";
export default function RosterSignupPanel({
  accounts,
  clans,
  hiddenTags,
  busy,
  error,
  trigger,
  onClose,
  onApply,
  onReviewChange,
}: {
  accounts: RosterAccount[];
  clans: RosterClan[];
  hiddenTags: string[];
  busy: boolean;
  error?: string;
  trigger: HTMLElement | null;
  onClose: () => void;
  onApply: (action: SignupAction, tags: string[]) => Promise<boolean>;
  onReviewChange: (value: boolean) => void;
}) {
  const [footerTarget, setFooterTarget] = useState<HTMLDivElement | null>(null);
  return (
    <ActionPanel
      title="Change signups"
      trigger={trigger}
      busy={busy}
      onClose={onClose}
      className="roster-ui"
      footer={
        <div
          className="action-panel-footer-target roster-signup-footer-target"
          ref={setFooterTarget}
        />
      }
    >
      <p>
        <StatusPill>{accounts.length} selected</StatusPill> Review changes
        before saving.
      </p>
      <RosterSignupActions
        accounts={accounts}
        clans={clans}
        hiddenTags={hiddenTags}
        busy={busy}
        error={error}
        footerTarget={footerTarget}
        onReviewChange={onReviewChange}
        onApply={async (action, tags) => {
          const success = await onApply(action, tags);
          if (success) onClose();
          return success;
        }}
      />
    </ActionPanel>
  );
}
