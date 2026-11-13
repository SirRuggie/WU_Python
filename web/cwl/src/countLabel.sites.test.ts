import { expect, it } from "vitest";
import { signupHeading } from "./MemberSignupStatus";

it("signupHeading singularizes one account", () => {
  expect(signupHeading(1, null)).toBe("✓ You are signed up · 1 account");
  expect(signupHeading(1, 1)).toBe("✓ You are signed up · all 1 account");
  expect(signupHeading(2, 2)).toBe("✓ You are signed up · all 2 accounts");
  expect(signupHeading(1, 3)).toBe("✓ You are signed up · 1 of 3 accounts");
});
