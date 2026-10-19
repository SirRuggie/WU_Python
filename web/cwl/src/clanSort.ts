export type ClanSort = 'name' | 'league_desc' | 'league_asc'
type Clan = { tag: string; name: string; cwl_league?: string | null }
export const clanSortOptions: {value: ClanSort; label: string}[] = [
  {value:'name',label:'Name A–Z'},
  {value:'league_desc',label:'CWL league: highest first'},
  {value:'league_asc',label:'CWL league: lowest first'},
]
function rank(league?: string | null): number | null {
  const match = /^(Bronze|Silver|Gold|Crystal|Master|Champion) League (III|II|I)$/i.exec(league?.trim() || '')
  if (!match) return null
  return ['bronze','silver','gold','crystal','master','champion'].indexOf(match[1].toLowerCase()) * 3 + ({III:0,II:1,I:2}[match[2].toUpperCase()] ?? 0)
}
export function sortClans<T extends Clan>(clans: T[], sort: ClanSort): T[] {
  return [...clans].sort((a,b)=>{
    const tie = () => a.name.localeCompare(b.name) || a.tag.localeCompare(b.tag)
    if(sort==='name') return tie()
    const left=rank(a.cwl_league), right=rank(b.cwl_league)
    if(left===null || right===null) {
      if(left!==null) return -1
      if(right!==null) return 1
      const unrankedA=a.cwl_league?.toLowerCase()==='unranked', unrankedB=b.cwl_league?.toLowerCase()==='unranked'
      return Number(unrankedB)-Number(unrankedA) || tie()
    }
    return (left-right)*(sort==='league_desc'?-1:1) || tie()
  })
}
