import type { Pool } from './api'
export type AnnouncementChannel = { id: string; name: string; type: number }
export function poolLabel(pool: Pool): string { return pool === 'main' ? 'Main Clan CWL' : 'Lazy CWL' }
