// Page-level notice for a browser issue reference. It lives outside React so
// it still shows when the app tree fails; Dismiss removes it until the next report.
export const ISSUE_NOTICE_ID = "dashboard-issue-reference";

export function showIssueNotice(reference: string) {
  let notice = document.getElementById(ISSUE_NOTICE_ID);
  if (!notice) {
    notice = document.createElement("div");
    notice.id = ISSUE_NOTICE_ID;
    notice.className = "notice error";
    notice.setAttribute("role", "alert");
    const text = document.createElement("span");
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", () => notice?.remove());
    notice.append(text, dismiss);
    document.body.prepend(notice);
  }
  notice.querySelector("span")!.textContent =
    `The browser reported a problem. Tell staff this reference: ${reference}`;
}
