import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; onFailure: () => void };
type State = { failed: boolean };

// The prank is optional. A failed lazy chunk must release the member tour.
export default class OwnerPrankBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onFailure();
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
