import ActionPanel from "./ActionPanel";
import RosterSignupActions, { type SignupAction } from "./RosterSignupActions";
import type { RosterAccount, RosterClan } from "./roster";
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
  return (
    <ActionPanel
      title="Change signups"
      trigger={trigger}
      busy={busy}
      onClose={onClose}
    >
      <p>{accounts.length} selected. Review changes before saving.</p>
      <RosterSignupActions
        accounts={accounts}
        clans={clans}
        hiddenTags={hiddenTags}
        busy={busy}
        error={error}
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
