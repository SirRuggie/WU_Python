// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import ClanFields from "./ClanFields";
import {
  clickOption,
  openPicker,
  optionTexts,
  pickerByLabel,
} from "../searchPickerTestUtils";
const leaderId = "123456789012345678";
const clan = {
  tag: "#AAA",
  revision: "one",
  name: "Test clan",
  type: "CWL",
  logo: "",
  leader_id: leaderId,
  leader_role_id: "",
  role_id: "",
};
it("shows leader name and avatar, with IDs only on hover, and shares ordered role search", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host),
    change = vi.fn();
  const props = {
    section: "Roles",
    draft: clan,
    saved: clan,
    disabled: false,
    dirty: false,
    data: { types: [], town_halls: [] },
    channels: [],
    roles: [
      { id: "9", name: "Bot integration", managed: true },
      { id: "3", name: "Captain", color: 0xff0000 },
      { id: "1", name: "Admiral" },
    ],
    memberQuery: "",
    setMemberQuery: vi.fn(),
    members: [
      {
        id: leaderId,
        name: "Captain Jane",
        avatar_url: "https://cdn.discordapp.com/embed/avatars/1.png",
      },
    ],
    memberError: "",
    change,
    action: vi.fn(),
    upload: vi.fn(),
  };
  try {
    await act(async () => root.render(<ClanFields {...props} />));
    expect(host.textContent).toContain("Captain Jane");
    expect(host.textContent).not.toContain(leaderId);
    expect(
      host
        .querySelector(".roster-discord-identity")!
        .getAttribute("aria-label"),
    ).toBe("Linked Discord member");
    expect(host.querySelector(".roster-discord-identity img")).not.toBeNull();
    const picker = pickerByLabel(host, "Find leader role");
    await openPicker(picker);
    expect(optionTexts(picker)).toEqual(["Captain", "Admiral"]);
    await clickOption(picker, "Captain");
    expect(change).toHaveBeenCalledWith("leader_role_id", "3");
    await act(async () => root.render(<ClanFields {...props} members={[]} />));
    expect(host.textContent).toContain("Current leader unavailable");
    expect(host.textContent).not.toContain(leaderId);
  } finally {
    act(() => root.unmount());
    host.remove();
  }
});

it("shows an unknown saved minimum Town Hall unchanged alongside registry choices", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const change = vi.fn();
  const current = { ...clan, th_requirements: "99", profile: "" };
  try {
    await act(async () =>
      root.render(
        <ClanFields
          section="Details"
          draft={current}
          saved={current}
          disabled={false}
          dirty={false}
          data={{ types: ["CWL"], town_halls: ["19", "18", "1"] }}
          channels={[]}
          roles={[]}
          memberQuery=""
          setMemberQuery={vi.fn()}
          members={[]}
          memberError=""
          change={change}
          action={vi.fn()}
          upload={vi.fn()}
        />,
      ),
    );
    const select = [...host.querySelectorAll<HTMLSelectElement>("select")].find(
      (node) => node.parentElement?.textContent?.includes("Minimum Town Hall"),
    )!;
    expect(select.value).toBe("99");
    expect(select.selectedOptions[0].textContent).toBe("TH 99");
    expect([...select.options].map((option) => option.value)).toEqual([
      "",
      "99",
      "19",
      "18",
      "1",
    ]);
    expect(change).not.toHaveBeenCalled();
    await act(async () => {
      select.value = "19";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(change).toHaveBeenCalledWith("th_requirements", "19");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
