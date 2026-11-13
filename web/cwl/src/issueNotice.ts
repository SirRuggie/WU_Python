// Page-level notice for a browser issue reference. It lives outside React so
// it still shows when the app tree fails; Dismiss removes it until the next report.
export const ISSUE_NOTICE_ID = "dashboard-issue-reference";
const ISSUE_STATUS_ID = `${ISSUE_NOTICE_ID}-status`;

// The copy result is announced from a separate status element, so the alert
// itself is not read out again.
function announceCopy(message: string) {
  let status = document.getElementById(ISSUE_STATUS_ID);
  if (!status) {
    status = document.createElement("span");
    status.id = ISSUE_STATUS_ID;
    status.setAttribute("role", "status");
    document.body.prepend(status);
  }
  status.textContent = message;
}

export function showIssueNotice(reference: string) {
  let notice = document.getElementById(ISSUE_NOTICE_ID);
  if (!notice) {
    notice = document.createElement("div");
    notice.id = ISSUE_NOTICE_ID;
    notice.className = "notice error";
    notice.setAttribute("role", "alert");
    const text = document.createElement("span");
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = "Copy";
    copy.setAttribute("aria-live", "off");
    copy.addEventListener("click", async () => {
      const reference = notice?.dataset.reference || "";
      try {
        await navigator.clipboard.writeText(reference);
        copy.textContent = "Copied";
        announceCopy("Reference copied");
      } catch {
        copy.textContent = "Could not copy";
        announceCopy("Could not copy. Select the reference to copy it.");
      }
    });
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", () => {
      notice?.remove();
      document.getElementById(ISSUE_STATUS_ID)?.remove();
    });
    notice.append(text, copy, dismiss);
    document.body.prepend(notice);
  }
  notice.dataset.reference = reference;
  notice.querySelector("button")!.textContent = "Copy";
  notice.querySelector("span")!.textContent =
    `The browser reported a problem. Tell staff this reference: ${reference}`;
}
