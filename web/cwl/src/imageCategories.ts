/** Gallery labels group storage paths without changing their keys or URLs. */
export function imageCategory(folder?:string):string {
 const root=(folder||'').trim().split('/').filter(Boolean)[0]||''
 const known:Record<string,string>={clans:'Clans',clan:'Clans','clan images':'Clans',fwa:'FWA',branding:'Branding',banners:'Branding',logos:'Branding',recruit:'Recruitment',recruitment:'Recruitment',tickets:'Tickets',content:'Triggers',triggers:'Triggers'}
 return known[root.toLowerCase()]||root.replace(/_/g,' ')
}
export const defaultImageCategories=['Clans','FWA','Branding','Recruitment','Tickets','Triggers']
