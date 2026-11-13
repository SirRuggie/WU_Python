// @vitest-environment happy-dom
import { describe, it, expect, afterEach } from "vitest";
import { showIssueNotice, ISSUE_NOTICE_ID } from "./issueNotice";

afterEach(() => {
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
    expect(notice.querySelector("button")!.textContent).toBe("Dismiss");
    expect(notice.querySelector("button")!.type).toBe("button");
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
    document.getElementById(ISSUE_NOTICE_ID)!.querySelector("button")!.click();
    expect(document.getElementById(ISSUE_NOTICE_ID)).toBeNull();
    showIssueNotice("ccc");
    expect(document.getElementById(ISSUE_NOTICE_ID)!.textContent).toContain(
      "ccc",
    );
  });
});
