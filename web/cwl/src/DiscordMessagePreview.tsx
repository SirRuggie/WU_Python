import { Component, lazy, Suspense, type ComponentProps, type ReactNode } from 'react'
import type Preview from './DiscordPreview'
import { reportBrowserIssue } from './api'
export type { PreviewPart } from './DiscordPreview'

const MessagePreview = lazy(() => import('./DiscordPreview'))

// A preview download/render failure must not unmount its parent's unsaved editor.
class PreviewBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { void reportBrowserIssue('browser_error') }
  render() {
    return this.state.failed
      ? <div className="discord-preview" role="alert">
          <p>Message preview couldn’t load. You can keep editing and save your changes, then reload to try the preview again.</p>
        </div>
      : this.props.children
  }
}

export default function DiscordMessagePreview(props: ComponentProps<typeof Preview>) {
  return <PreviewBoundary>
    <Suspense fallback={<p className="discord-preview" role="status">Loading message preview…</p>}>
      <MessagePreview {...props} />
    </Suspense>
  </PreviewBoundary>
}
