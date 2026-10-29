import type { RefObject } from "react";
import type { Pool } from "./api";
import "./SignupWalkthrough.css";

export type SignupStage = 1 | 2 | 3;
type Props = {
  stage: SignupStage;
  pool: Pool | null;
  selectedCount: number;
  busy: boolean;
  canReview: boolean;
  headingRef: RefObject<HTMLHeadingElement | null>;
  onNavigate: (stage: SignupStage) => void;
};

export default function SignupWalkthrough({
  stage,
  pool,
  selectedCount,
  busy,
  canReview,
  headingRef,
  onNavigate,
}: Props) {
  const poolLabel =
    pool === "main" ? "Main CWL" : pool === "lazy" ? "Lazy CWL" : "CWL";
  const steps = [
    {
      number: 1 as const,
      title: "Choose your CWL",
      summary: "Main or Lazy CWL",
      instruction:
        "Choose Main or Lazy CWL. You can choose a different option for each account.",
      art: "villager-52545",
      available: true,
    },
    {
      number: 2 as const,
      title: "Select your accounts",
      summary: `You’re signing up for ${poolLabel} · ${selectedCount} selected`,
      instruction: `Select the accounts you want to sign up for ${poolLabel}.`,
      art: "villager-52538",
      available: !!pool,
    },
    {
      number: 3 as const,
      title: "Check and sign up",
      summary: "Not saved yet",
      instruction: "Check your accounts. Select Sign up below to finish.",
      art: "villager-52543",
      available: canReview,
    },
  ];
  return (
    <nav className="signup-walkthrough" aria-label="Signup walkthrough">
      <ol>
        {steps.map((step) => (
          <li
            key={step.number}
            className={stage === step.number ? "current" : ""}
          >
            <h2
              ref={stage === step.number ? headingRef : undefined}
              tabIndex={-1}
            >
              <button
                type="button"
                aria-current={stage === step.number ? "step" : undefined}
                disabled={busy || !step.available}
                onClick={() => onNavigate(step.number)}
              >
                <span className="walkthrough-step">
                  Step {step.number} of 3{stage !== step.number && " · "}
                </span>
                <span className="walkthrough-title">{step.title}</span>
                {stage === step.number && (
                  <span className="walkthrough-summary">{step.summary}</span>
                )}
              </button>
            </h2>
            {stage === step.number && (
              <p className="walkthrough-instruction">{step.instruction}</p>
            )}
            {stage === step.number && (
              <img
                className="walkthrough-art"
                src={`/assets/tour/${step.art}.webp`}
                alt=""
                loading="lazy"
                height={120}
              />
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
