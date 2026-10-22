import { Component, Suspense, type ReactNode } from 'react'
import { reportBrowserIssue } from './api'

type Props = { children: ReactNode; resetKey: string }
type State = { failed: boolean; resetKey: string }

class ScreenErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, resetKey: this.props.resetKey }

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.resetKey
      ? { failed: false, resetKey: props.resetKey }
      : null
  }

  componentDidCatch() {
    reportBrowserIssue('browser_error')
  }

  render() {
    if (this.state.failed) {
      return <section className="panel" role="alert">
        <h2>This screen couldn’t load</h2>
        <p>Try another screen from the menu, or reload the dashboard. Reloading may discard unsaved edits.</p>
        <button type="button" onClick={() => window.location.reload()}>Reload dashboard</button>
      </section>
    }
    return this.props.children
  }
}

export default function RouteLoadBoundary({ children, resetKey }: Props) {
  return <ScreenErrorBoundary resetKey={resetKey}>
    <Suspense fallback={<p role="status">Loading screen…</p>}>
      {children}
    </Suspense>
  </ScreenErrorBoundary>
}
