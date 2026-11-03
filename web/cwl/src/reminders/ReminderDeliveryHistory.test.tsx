// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import ReminderDeliveryHistory from "./ReminderDeliveryHistory";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("renders actual send time and plain late/deleted labels while escaping external errors", async () => {
  await act(async () =>
    root.render(
      <ReminderDeliveryHistory
        history={[
          {
            message_key: "signup",
            variant: "main",
            status: "sent",
            late: true,
            at: "2026-11-20T17:00:00Z",
            original_due_at: "2026-11-20T16:59:00Z",
          },
          {
            message_key: "roster",
            variant: "lazy",
            status: "deleted_confirmed",
            at: "2026-11-20T17:00:00Z",
          },
          {
            message_key: "reminder:1",
            variant: "lazy",
            status: "failed",
            reason: "<img src=external onerror=send()>",
          },
        ]}
      />,
    ),
  );
  expect(host.textContent).toContain("Main · Sent late");
  expect(host.textContent).toContain("Lazy · Post deleted");
  expect(host.textContent).not.toContain("deleted_confirmed");
  expect(host.querySelector("time")?.dateTime).toBe("2026-11-20T17:00:00Z");
  expect(host.textContent).toContain("Scheduled");
  expect(host.querySelector("img")).toBeNull();
  expect(host.textContent).toContain("<img src=external onerror=send()>");
});

it("distinguishes unavailable history, empty history and malformed partial rows", async () => {
  await act(async () => root.render(<ReminderDeliveryHistory />));
  expect(host.textContent).toBe("Delivery history unavailable.");
  await act(async () => root.render(<ReminderDeliveryHistory history={[]} />));
  expect(host.textContent).toContain("No recorded delivery activity");
  await act(async () =>
    root.render(
      <ReminderDeliveryHistory
        history={[null] as unknown as Record<string, unknown>[]}
      />,
    ),
  );
  expect(host.textContent).toContain("Status unavailable");
  expect(host.textContent).toContain("Time unavailable");
});
