// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import ModerationDestinationPicker from "./ModerationDestinationPicker";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("shows the selected destination by name without its id", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <ModerationDestinationPicker
        label="Destination"
        value={{ channel_id: "140000000000000001", forum_tag_id: null }}
        channels={[
          {
            id: "140000000000000001",
            name: "Message Logs",
            type: "text",
            available_tags: [],
            can_post: true,
            requires_tag: false,
            can_manage_threads: false,
          },
        ]}
        disabled={false}
        onChange={vi.fn()}
        onResolve={vi.fn()}
      />,
    ),
  );
  const input = host.querySelector<HTMLInputElement>("input")!;
  expect(input.value).toBe("#Message Logs");
  expect(input.value).not.toContain("1400000");
  await act(async () => root.unmount());
  host.remove();
});
