import FilterChips from "../FilterChips";
const preferred = ['Tactical', 'Flexible Fun', 'FWA', 'CWL']
export const clanCategory = (value: string) => value.toLowerCase() === 'farming' ? 'FWA' : value

export default function ClanCategories({ clans, value, onChange }: {
  clans: { type: string }[]; value: string; onChange: (value: string) => void
}) {
  const categories = [...new Set([...preferred, ...clans.map(clan => clanCategory(clan.type)).filter(Boolean)])]
  return <FilterChips
           className="clan-category-filters filter-chips--flow"
           label="Clan categories"
           options={["", ...categories].map((category) => {
             return {
               value: category,
               label: <>{category || "All clans"}</>,
               count: category
                 ? clans.filter((clan) => clanCategory(clan.type) === category).length
                 : clans.length,
             };
           })}
           value={value}
           onChange={(category) => {
             onChange(category);
           }}
           variant="pill"
           role="group"
           revealSelection
         />
}
