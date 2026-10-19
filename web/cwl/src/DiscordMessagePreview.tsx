import {lazy,Suspense} from 'react'
import type {ComponentProps} from 'react'
import type Preview from './DiscordPreview'
export type {PreviewPart} from './DiscordPreview'
const MessagePreview=lazy(()=>import('./DiscordPreview'))
export default function DiscordMessagePreview(props:ComponentProps<typeof Preview>){return <Suspense fallback={<p role="status">Loading message preview…</p>}><MessagePreview {...props}/></Suspense>}
