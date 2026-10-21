const preferred = ['Tactical', 'Flexible Fun', 'FWA', 'CWL']
export const clanCategory = (value: string) => value.toLowerCase() === 'farming' ? 'FWA' : value

export default function ClanCategories({ clans, value, onChange }: {
  clans: { type: string }[]; value: string; onChange: (value: string) => void
}) {
  const categories = [...new Set([...preferred, ...clans.map(clan => clanCategory(clan.type)).filter(Boolean)])]
  return <div className="clan-category-filters" role="group" aria-label="Clan categories">
    {['', ...categories].map(category => <button type="button" key={category}
      aria-pressed={value === category} onClick={() => onChange(category)}>
      {category || 'All clans'} <span>{category ? clans.filter(clan => clanCategory(clan.type) === category).length : clans.length}</span>
    </button>)}
  </div>
}
