// @vitest-environment happy-dom
import { describe, it, expect, afterEach, vi } from "vitest";
import { showIssueNotice, ISSUE_NOTICE_ID } from "./issueNotice";

const dismissButton = () =>
  [
    ...document.getElementById(ISSUE_NOTICE_ID)!.querySelectorAll("button"),
  ].find((button) => button.textContent === "Dismiss")!;
afterEach(() => {
  document.getElementById(`${ISSUE_NOTICE_ID}-status`)?.remove();
  document.getElementById(ISSUE_NOTICE_ID)?.remove();
});
describe("issue notice", () => {
  it("shows the reference with a Dismiss control", () => {
    showIssueNotice("477da595ac01");
    const notice = document.getElementById(ISSUE_NOTICE_ID)!;
    expect(notice.getAttribute("role")).toBe("alert");
    expect(notice.textContent).toContain(
      "Tell staff this reference: 477da595ac01",
    );
    expect(dismissButton().textContent).toBe("Dismiss");
    expect(dismissButton().type).toBe("button");
  });
  it("copies the reference and announces it outside the alert", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: write },
      configurable: true,
    });
    showIssueNotice("477da595ac01");
    const notice = document.getElementById(ISSUE_NOTICE_ID)!;
    const copy = notice.querySelector("button")!;
    expect(copy.textContent).toBe("Copy");
    copy.click();
    await Promise.resolve();
    await Promise.resolve();
    expect(write).toHaveBeenCalledWith("477da595ac01");
    expect(copy.textContent).toBe("Copied");
    const status = document.getElementById(`${ISSUE_NOTICE_ID}-status`)!;
    expect(status.getAttribute("role")).toBe("status");
    expect(status.textContent).toBe("Reference copied");
    expect(notice.contains(status)).toBe(false);
    dismissButton().click();
    expect(document.getElementById(`${ISSUE_NOTICE_ID}-status`)).toBeNull();
  });
  it("updates one notice instead of stacking", () => {
    showIssueNotice("aaa");
    showIssueNotice("bbb");
    expect(document.querySelectorAll(`#${ISSUE_NOTICE_ID}`)).toHaveLength(1);
    expect(document.getElementById(ISSUE_NOTICE_ID)!.textContent).toContain(
      "bbb",
    );
    expect(document.getElementById(ISSUE_NOTICE_ID)!.textContent).not.toContain(
      "aaa",
    );
  });
  it("Dismiss removes the notice and a later report shows it again", () => {
    showIssueNotice("aaa");
    dismissButton().click();
    expect(document.getElementById(ISSUE_NOTICE_ID)).toBeNull();
    showIssueNotice("ccc");
    expect(document.getElementById(ISSUE_NOTICE_ID)!.textContent).toContain(
      "ccc",
    );
  });
});
