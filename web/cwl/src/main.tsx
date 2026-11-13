import "./tokens.css";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { reportBrowserIssue } from "./api";
window.addEventListener("error", () => {
  void reportBrowserIssue("browser_error");
});
window.addEventListener("unhandledrejection", () => {
  void reportBrowserIssue("unhandled_promise");
});
import "./style.css";
import "./workflowControls.css";
import "./accessibility.css";
import { registerPushWorker } from "./webPush";
import { showIssueNotice } from "./issueNotice";

// Installation support is passive; notification permission remains opt-in.
if ("serviceWorker" in navigator && window.isSecureContext) {
  void registerPushWorker().catch(() => {
    /* The dashboard still works when workers are blocked. */
  });
}

window.addEventListener("dashboard-issue", ((event: CustomEvent<string>) => {
  showIssueNotice(event.detail);
}) as EventListener);

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
