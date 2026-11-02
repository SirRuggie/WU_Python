import { membersText as t } from "./strings";
import "./Members.css";
import SelectionActionBar from "../SelectionActionBar";
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
  const actions = [
    ...(canRoles
      ? [
          { id: "add", label: t.addRole, onAction: onAdd, disabled: busy },
          {
            id: "remove",
            label: t.removeRole,
            onAction: onRemove,
            disabled: busy,
          },
        ]
      : []),
    ...(canProfiles
      ? [{ id: "fix", label: t.fixNames, onAction: onFix, disabled: busy }]
      : []),
  ];
  return (
    <SelectionActionBar
      name={t.selectionLabel}
      label={t.selected(count, hidden)}
      shortLabel={t.selectedShort(count, hidden)}
      onShow={onShow}
      actions={actions}
      selectionActions={[
        {
          id: "page",
          label: pageSelected ? t.unselectPage : t.selectPage,
          onAction: onSelectPage,
        },
        {
          id: "matching",
          label: t.selectMatching(matchingCount),
          onAction: onSelectMatching,
        },
        { id: "clear", label: t.selectNone, onAction: onClear },
      ]}
      desktopSelection={
        <>
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
        </>
      }
    />
  );
}
