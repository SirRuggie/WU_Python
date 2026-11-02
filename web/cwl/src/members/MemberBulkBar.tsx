import { membersText as t } from "./strings";
import "./Members.css";
export default function MemberBulkBar({
  pageSelected,
  pagePartial,
  onSelectPage,
  matchingCount,
  onSelectMatching,
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
  pageSelected: boolean;
  pagePartial: boolean;
  onSelectPage: () => void;
  matchingCount: number;
  onSelectMatching: () => void;
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
      <button onClick={onClear}>{t.selectNone}</button>
      <label className="members-checkbox">
        <input
          type="checkbox"
          aria-label={t.selectPage}
          checked={pageSelected}
          ref={(node) => {
            if (node) node.indeterminate = pagePartial;
          }}
          onChange={onSelectPage}
        />
        {t.selectPage}
      </label>
      <button onClick={onSelectMatching}>
        {t.selectMatching(matchingCount)}
      </button>
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
    </div>
  );
}
