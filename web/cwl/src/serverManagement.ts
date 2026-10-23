import type {PreviewPart} from './DiscordPreview'
export type ManagementValue = string | number | boolean | string[] | null
export type ManagementOption = {value: string; label: string}
export type ManagementField = {key: string; label: string; type: 'text'|'textarea'|'number'|'boolean'|'select'|'channel'|'role'|'member'|'multiselect'; value: ManagementValue; description?: string; source?: 'roles'|'members'|'channels'; options?: ManagementOption[]; required?: boolean; min?: number; max?: number; max_length?: number; readonly?: boolean; placeholder?: string; upload_label?: string; upload_endpoint?: string; upload_max_bytes?: number}
export type ReturnStatus = {starts_at?: string | null; list_expires_at?: string | null;state: string; label: string; players: number; expires_at: string | null; last_sent_at: string | null; every_minutes: number | null}
export type ManagementSection = {return_status?: ReturnStatus;id: string; label: string; description: string; group: string; allowed?: boolean; endpoint?: string; destination?: string}
export type ManagementDocument = ManagementSection & {member_refresh?: number; action_only?: boolean; documents?: ManagementSection[]; revision: string | number; fields: ManagementField[]; publish_endpoint?: string|null; preview_supported?: boolean; preview?: PreviewPart[]; warning?: string; readonly?: boolean; actions?: {advanced?: boolean;id: string;label: string;description?: string;confirm?: string;endpoint?: string}[]}
export function fieldValues(fields: ManagementField[]): Record<string, ManagementValue> {return Object.fromEntries(fields.map(field=>[field.key,field.value]))}
export function changedValues(fields: ManagementField[], draft: Record<string,ManagementValue>) {return Object.fromEntries(fields.filter(field=>JSON.stringify(field.value)!==JSON.stringify(draft[field.key])).map(field=>[field.key,draft[field.key]]))}
export function filterSections(sections: ManagementSection[], query: string) {const words=query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);return sections.filter(section=>section.allowed!==false&&words.every(word=>`${section.label} ${section.description} ${section.group}`.toLocaleLowerCase().includes(word)))}
export function fieldError(field: ManagementField,value: ManagementValue): string | null {if(field.required&&(value===null||value===''||(Array.isArray(value)&&!value.length)))return `${field.label} is required.`;if(field.type==='number'&&value!==''&&value!==null){const number=Number(value);if(!Number.isFinite(number))return `Enter a number for ${field.label}.`;if(field.min!==undefined&&number<field.min)return `${field.label} must be ${field.min} or more.`;if(field.max!==undefined&&number>field.max)return `${field.label} must be ${field.max} or less.`}return null}

export class ManagementRequestIds {
 private ids = new Map<string,string>()
 constructor(private create:()=>string=()=>crypto.randomUUID()) {}
 key(endpoint:string, revision:string|number, values:Record<string,ManagementValue>) {return JSON.stringify([endpoint,revision,Object.keys(values).sort().map(key=>[key,values[key]])])}
 get(key:string) {let value=this.ids.get(key);if(!value){value=this.create();this.ids.set(key,value)}return value}
 complete(key:string) {this.ids.delete(key)}
}

export type ManagementResult = {message?:string;url?:string;details?:string;accounts?:{name?:string;player_name?:string;tag?:string;player_tag?:string;current_clan?:string|{name?:string;tag?:string};current_clan_name?:string;clan_name?:string;clan?:{name?:string;tag?:string}}[]}
export function safeDiscordUrl(value?:string):string|null {if(!value)return null;try{const url=new URL(value);return url.protocol==='https:'&&url.hostname==='discord.com'&&/^\/channels\/\d+\/\d+(?:\/\d+)?\/?$/.test(url.pathname)&&!url.username&&!url.password?url.href:null}catch{return null}}

export function actionConfirmation(prompt:string,fields:ManagementField[],draft:Record<string,ManagementValue>):string {
 const member=fields.find(field=>field.key==='member_id')
 if(member&&draft.member_id){const name=member.options?.find(option=>option.value===draft.member_id)?.label||String(draft.member_id);const roleField=fields.find(field=>field.key==='role_ids');const roles=Array.isArray(draft.role_ids)?draft.role_ids.map(id=>roleField?.options?.find(option=>option.value===id)?.label||id):[];return `${prompt}\n\nMember: ${name}\nRoles: ${roles.join(', ')}`}
 const clans=fields.find(field=>field.key==='clans')
 const selected=draft.clans
 if(!clans||!Array.isArray(selected))return prompt
 const names=selected.map(value=>clans.options?.find(option=>option.value===value)?.label||value)
 return `${prompt}\n\n${names.length} clans selected:\n${names.join('\n')}`
}

export function recordPickerCopy(records:ManagementSection[]) {
 const paths=records.map(record=>record.endpoint||'').join(' ')
 if(paths.includes('/ticket-settings/'))return {label:'Ticket settings',search:'Search ticket settings',placeholder:'Channels, wait times or staff access'}
 if(/\/fwa_(weight|bases)\//.test(paths))return {label:'Town Hall settings',search:'Search Town Hall settings',placeholder:'Town Hall level'}
 if(paths.includes('/fwa_blacklist/'))return {label:'Blocked clan',search:'Search blocked clans',placeholder:'Clan name or tag'}
 if(paths.includes('/fwa_points/'))return {label:'Clan or points settings',search:'Search clans or points settings',placeholder:'Clan name, tag or monitoring'}
 if(paths.includes('/return-batches/'))return {label:'Previous bulk action',search:'Search previous bulk actions',placeholder:'Action or date'}
 if(paths.includes('/return-'))return {label:'Clan or reminder setting',search:'Search clans or reminder settings',placeholder:'Clan name, tag or action'}
 return {label:'Setting',search:'Search settings',placeholder:'Setting name'}
}


/** Only known read-only bot checks can bypass mutation confirmation. */
export function actionNeedsConfirmation(documentId: string, actionId: string): boolean {
 return !((documentId === 'band_monitor' && actionId === 'status') ||
   (documentId === 'fwa_sync' && actionId === 'check_feed'))
}
