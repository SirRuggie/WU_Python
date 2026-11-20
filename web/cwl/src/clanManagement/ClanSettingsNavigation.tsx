import SectionTabs from "../SectionTabs";

type Props<T extends string> = {
  sections: readonly T[];
  value: T;
  disabled: boolean;
  onChange: (value: T) => void;
};

export default function ClanSettingsNavigation<T extends string>({
  sections,
  value,
  disabled,
  onChange,
}: Props<T>) {
  return (
    <SectionTabs
      id="clan-settings"
      allPanelsMounted
      className="clan-tabs section-tabs--flow"
      label="Clan settings"
      items={sections.map((section, index) => ({
        id: section,
        label: section,
        tabId: `clan-section-${index}`,
        panelId: `clan-panel-${index}`,
      }))}
      value={value}
      disabled={disabled}
      onChange={onChange}
      revealSelection
    />
  );
}
