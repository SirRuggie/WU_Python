import MemberSignupStatus from "./MemberSignupStatus";
import { useJourneyState } from "./journeyState";
import type { ComponentProps } from "react";

type Props = ComponentProps<typeof MemberSignupStatus> & { sessionKey: string };
export default function HomeSignupSummary({ sessionKey, ...props }: Props) {
  const [shown, setShown] = useJourneyState(
    `home-signup-summary:${sessionKey}`,
    false,
  );
  if (!props.signups.length) return <MemberSignupStatus {...props} />;
  return (
    <details
      className="home-signup-summary"
      open={shown}
      onToggle={(event) => setShown(event.currentTarget.open)}
    >
      <summary>
        <span>
          ✓ Signed up · {props.signups.length} of{" "}
          {props.accounts?.length ?? props.signups.length} accounts
        </span>
        <span>{shown ? "Hide" : "Show"}</span>
      </summary>
      {shown && <MemberSignupStatus {...props} />}
    </details>
  );
}
