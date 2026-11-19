// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Form from "./ManagementEditorForm";
import type { ManagementDocument, ManagementValue } from "./serverManagement";
import { fieldValues } from "./serverManagement";
import { api } from "./api";
import {
  openPicker,
  clickOption,
  pickerByLabel,
  pickerValue,
} from "./searchPickerTestUtils";
vi.mock("./api", () => ({ api: vi.fn(), apiUpload: vi.fn() }));
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.mocked(api).mockReset().mockResolvedValue({ emojis: [], errors: {} });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const base: ManagementDocument = {
  id: "town_halls",
  label: "Town Hall 19",
  description: "",
  group: "Clan resources",
  revision: 7,
  level: 19,
  fields: [
    {
      key: "emoji",
      label: "Town Hall emoji",
      type: "emoji",
      value: "",
      group: "Town Hall",
    },
    {
      key: "min",
      label: "Minimum weight",
      type: "number",
      value: 181000,
      group: "Town Hall",
    },
    {
      key: "max",
      label: "Maximum weight",
      type: "number",
      value: 190000,
      group: "Town Hall",
    },
  ],
};
function Sample({
  document = base,
  dirty = true,
  save = vi.fn(),
  open = vi.fn(),
}: {
  document?: ManagementDocument;
  dirty?: boolean;
  save?: () => void;
  open?: (endpoint: string) => void;
}) {
  const [draft, setDraft] = useState<Record<string, ManagementValue>>(() =>
    fieldValues(document.fields),
  );
  return (
    <Form
      selected={document}
      document={document}
      draft={draft}
      busy={false}
      dirty={dirty}
      conflict={false}
      publishDirty={false}
      statusUrl=""
      fieldPage={0}
      compactPreview={false}
      operationsWorkspace={false}
      onSave={save}
      onOpenRecord={open}
      setFieldPage={vi.fn()}
      setMobilePane={vi.fn()}
      setDocument={vi.fn()}
      setDraft={setDraft}
      setNotice={vi.fn()}
    />
  );
}

it("shows visible fieldsets, no grouped paging and the live weight pair helper", async () => {
  const document = {
    ...base,
    fields: [
      ...base.fields,
      ...Array.from({ length: 5 }, (_, index) => ({
        key: `extra${index}`,
        label: `Extra ${index}`,
        type: "text" as const,
        value: "",
        group: "Town Hall",
      })),
    ],
  };
  await act(async () => root.render(<Sample document={document} />));
  expect(
    [...host.querySelectorAll("legend")].some(
      (node) => node.textContent === "Town Hall",
    ),
  ).toBe(true);
  expect(host.textContent).not.toContain("Message or setting to edit");
  expect(host.querySelectorAll(".town-hall-weight-pair input")).toHaveLength(2);
  expect(host.textContent).toContain("Shows as 181k – 190k");
  const minimum = host.querySelector<HTMLInputElement>("#manage-min")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(minimum, "182000");
    minimum.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.textContent).toContain("Shows as 182k – 190k");
});

it("retains paging for ungrouped documents above six fields", async () => {
  const document = {
    ...base,
    id: "other",
    fields: Array.from({ length: 8 }, (_, index) => ({
      key: `field${index}`,
      label: `Field ${index}`,
      type: "text" as const,
      value: "",
    })),
  };
  await act(async () => root.render(<Sample document={document} />));
  expect(host.textContent).toContain("Message or setting to edit");
  expect(host.querySelectorAll("input")).toHaveLength(4);
});

it("enables Add with untouched prefilled values and gives the duplicate its inline link", async () => {
  const add: ManagementDocument = {
    ...base,
    label: "Add Town Hall",
    create: true,
    submit_label: "Add Town Hall",
    fields: [
      {
        key: "level",
        label: "Town Hall level",
        type: "number",
        value: 20,
        min: 1,
        max: 99,
      },
      { key: "emoji", label: "Town Hall emoji", type: "emoji", value: "" },
    ],
    documents: [
      {
        id: "19",
        label: "Town Hall 19",
        description: "",
        group: "",
        list_role: "level",
      },
    ],
  };
  const save = vi.fn(),
    open = vi.fn();
  await act(async () =>
    root.render(
      <Sample document={add} dirty={false} save={save} open={open} />,
    ),
  );
  const button = host.querySelector<HTMLButtonElement>(
    'button[type="submit"]',
  )!;
  expect(button.textContent).toBe("Add Town Hall");
  expect(button.disabled).toBe(false);
  await act(async () => button.click());
  expect(save).toHaveBeenCalledTimes(1);
  const level = host.querySelector<HTMLInputElement>("#manage-level")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(level, "19");
    level.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(button.disabled).toBe(true);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "This Town Hall is already in the list. Open it to edit.",
  );
  await act(async () =>
    host.querySelector<HTMLAnchorElement>('[role="alert"] a')!.click(),
  );
  expect(open).toHaveBeenCalledWith("/manage/town-halls/19");
});

it("recovers Add suggestions after failed prefetch and successful picker retry without overriding a manual choice", async () => {
  const emojis = [
    {
      value: "<:TH_20:123456789012345678>",
      name: "TH_20",
      source: "bot",
      available: true,
      image_url:
        "https://cdn.discordapp.com/emojis/123456789012345678.webp?size=48",
    },
    {
      value: "<:TH_21A:123456789012345679>",
      name: "TH_21A",
      source: "bot",
      available: true,
      image_url:
        "https://cdn.discordapp.com/emojis/123456789012345679.webp?size=48",
    },
    {
      value: "<:Manual:123456789012345680>",
      name: "Manual",
      source: "server",
      available: true,
      image_url:
        "https://cdn.discordapp.com/emojis/123456789012345680.webp?size=48",
    },
  ];
  vi.mocked(api)
    .mockReset()
    .mockRejectedValueOnce(new Error("503"))
    .mockResolvedValueOnce({ emojis, errors: {} });
  const add = {
    ...base,
    create: true,
    fields: [
      {
        key: "level",
        label: "Town Hall level",
        type: "number" as const,
        value: 20,
      },
      {
        key: "emoji",
        label: "Town Hall emoji",
        type: "emoji" as const,
        value: "",
      },
    ],
  };
  await act(async () => root.render(<Sample document={add} dirty={false} />));
  expect(host.textContent).toContain("Emojis could not load. Try again.");
  const picker = pickerByLabel(host, "Town Hall emoji");
  await openPicker(picker);
  expect(api).toHaveBeenCalledTimes(2);
  expect(pickerValue(picker)).toContain("TH_20");
  expect(host.textContent).toContain(
    "Found a bot emoji for this level. Save to confirm it.",
  );
  expect(host.textContent).not.toContain("Emojis could not load.");
  const level = host.querySelector<HTMLInputElement>("#manage-level")!;
  async function setLevel(value: string) {
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(level, value);
      level.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  await setLevel("21");
  expect(pickerValue(picker)).toContain("TH_21A");
  await clickOption(picker, "Manual");
  await setLevel("20");
  expect(pickerValue(picker)).toContain("Manual");
  expect(host.textContent).not.toContain("Found a bot emoji");
  expect(api).toHaveBeenCalledTimes(2);
});

it("shares the in-flight Add prefetch with an opened picker", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const add = {
    ...base,
    create: true,
    fields: [
      {
        key: "level",
        label: "Town Hall level",
        type: "number" as const,
        value: 20,
      },
      {
        key: "emoji",
        label: "Town Hall emoji",
        type: "emoji" as const,
        value: "",
      },
    ],
  };
  await act(async () => root.render(<Sample document={add} dirty={false} />));
  await openPicker(pickerByLabel(host, "Town Hall emoji"));
  expect(api).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("Loading emojis…");
  await act(async () => finish({ emojis: [], errors: {} }));
  expect(api).toHaveBeenCalledTimes(1);
});
