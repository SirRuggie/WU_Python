import { membersText as t } from "./strings";
import "./Members.css";
export default function MemberBulkBar({
  count,
  hidden,
  canRoles,
  canProfiles,
  busy,
  onShow,
  onAdd,
  onRemove,
  onFix,
  onClear,
}: {
  count: number;
  hidden: number;
  canRoles: boolean;
  canProfiles: boolean;
  busy: boolean;
  onShow: () => void;
  onAdd: () => void;
  onRemove: () => void;
  onFix: () => void;
  onClear: () => void;
}) {
  if (!count) return null;
  return (
    <div
      className="members-bulk-bar"
      role="region"
      aria-label={t.selectionLabel}
    >
      <button onClick={onShow}>{t.selected(count, hidden)}</button>
      {canRoles && (
        <>
          <button disabled={busy} onClick={onAdd}>
            {t.addRole}
          </button>
          <button disabled={busy} onClick={onRemove}>
            {t.removeRole}
          </button>
        </>
      )}
      {canProfiles && (
        <button disabled={busy} onClick={onFix}>
          {t.fixNames}
        </button>
      )}
      <button disabled={busy} onClick={onClear}>
        {t.selectNone}
      </button>
    </div>
  );
}
