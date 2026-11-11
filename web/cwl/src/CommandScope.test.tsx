// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import CommandScope from "./CommandScope";
import type { Command } from "./CommandBuilder";
import {
  pickOption,
  pickerByLabel,
  pickerValue,
} from "./searchPickerTestUtils";
it("adds and removes named roles without selecting anyone by default", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  function Example() {
    const [draft, setDraft] = useState<Command>({
      command: "!test",
      enabled: true,
      text: "x",
      title: "",
      description: "",
      image_url: "",
      color: "#ffffff",
    });
    return (
      <CommandScope
        draft={draft}
        channels={[]}
        roles={[{ id: "123", name: "Member" }]}
        disabled={false}
        onChange={(key, value) => setDraft({ ...draft, [key]: value })}
      />
    );
  }
  try {
    await act(async () => root.render(<Example />));
    const picker = pickerByLabel(host, "Only for these roles");
    expect(pickerValue(picker)).toBe("Select a role");
    await pickOption(picker, "Member");
    expect(host.textContent).toContain("Remove Member");
    await act(async () => {
      (
        [...host.querySelectorAll("button")].find(
          (b) => b.textContent === "Remove Member",
        ) as HTMLButtonElement
      ).click();
    });
    expect(host.textContent).not.toContain("Remove Member");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
