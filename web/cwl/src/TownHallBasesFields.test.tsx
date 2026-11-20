// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Form from "./ManagementEditorForm";
import { api, apiUpload } from "./api";
import {
  fieldValues,
  type ManagementDocument,
  type ManagementField,
  type ManagementValue,
} from "./serverManagement";
vi.mock("./api", () => ({ api: vi.fn(), apiUpload: vi.fn() }));
let root: Root, host: HTMLDivElement;
const link = "https://link.clashofclans.com/en?action=OpenLayout&id=fixture";
function documentFor(weight = true, bases = true): ManagementDocument {
  const fields: ManagementField[] = [
    {
      key: "emoji",
      label: "Town Hall emoji",
      type: "emoji",
      value: "<:TH19:123456789012345678>",
      group: "Town Hall",
      readonly: !weight,
    },
    {
      key: "min",
      label: "Minimum weight",
      type: "number",
      value: 181000,
      group: "Town Hall",
      readonly: !weight,
    },
    {
      key: "max",
      label: "Maximum weight",
      type: "number",
      value: 190000,
      group: "Town Hall",
      readonly: !weight,
    },
    ...(["war_image", "active_image"] as const).map((slot) => ({
      key: `bases.${slot}`,
      label: slot === "war_image" ? "War base image" : "Active base image",
      type: "text" as const,
      value: "https://images.example/shared.jpg",
      group: "Base images",
      readonly: !bases,
      ...(bases
        ? {
            upload_endpoint: `/manage/town-halls/19/upload/${slot}`,
            upload_label: "Upload image",
          }
        : {}),
    })),
    ...(["merged", "non_merged"] as const).flatMap((variant) =>
      (["link", "instructions", "upgrade_notes"] as const).map((key) => ({
        key: `bases.${variant}.${key}`,
        label:
          key === "link"
            ? "Base link"
            : key === "instructions"
              ? "Base instructions"
              : "Upgrade notes",
        type: key === "link" ? ("text" as const) : ("textarea" as const),
        value:
          key === "link" && variant === "merged"
            ? link
            : key === "link"
              ? ""
              : "Sample notes",
        group: variant === "merged" ? "Merged" : "Non-merged",
        readonly: !bases,
      })),
    ),
  ];
  return {
    id: "town_halls",
    label: "Town Hall 19",
    description: "",
    group: "Clan resources",
    revision: 7,
    level: 19,
    fields,
    base_management: true,
    partial_save: true,
    emoji_url:
      "https://cdn.discordapp.com/emojis/123456789012345678.webp?size=64",
    section_readonly: {
      "Town Hall": !weight,
      "Base images": !bases,
      Merged: !bases,
      "Non-merged": !bases,
    },
    base_status: { Merged: true, "Non-merged": false },
  };
}
function Sample({ document }: { document: ManagementDocument }) {
  const [draft, setDraft] = useState<Record<string, ManagementValue>>(() =>
    fieldValues(document.fields),
  );
  return (
    <Form
      selected={document}
      document={document}
      draft={draft}
      busy={false}
      dirty
      conflict={false}
      publishDirty={false}
      statusUrl=""
      fieldPage={0}
      compactPreview={false}
      operationsWorkspace={false}
      onSave={vi.fn()}
      setFieldPage={() => {}}
      setMobilePane={() => {}}
      setDocument={() => {}}
      setDraft={setDraft}
      setNotice={() => {}}
    />
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.mocked(api).mockReset().mockResolvedValue({ emojis: [], errors: {} });
  vi.mocked(apiUpload)
    .mockReset()
    .mockResolvedValue({ url: "https://images.example/uploaded.jpg" });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const section = (name: string) =>
  [...host.querySelectorAll<HTMLFieldSetElement>(".manage-field-group")].find(
    (node) => node.querySelector("legend")?.firstChild?.textContent === name,
  )!;
const input = (name: string) =>
  [...host.querySelectorAll("label")].find((node) => node.textContent === name)
    ?.control as HTMLInputElement;
it("renders four visible legends without paging and keeps status tied to saved links", async () => {
  const doc = documentFor();
  await act(async () => root.render(<Sample document={doc} />));
  expect(
    [...host.querySelectorAll(".manage-field-group > legend")].map(
      (node) => node.firstChild?.textContent,
    ),
  ).toEqual(["Town Hall", "Base images", "Merged", "Non-merged"]);
  expect(host.textContent).not.toContain("Message or setting to edit");
  expect(section("Merged").textContent).toContain("Shown to members");
  const draft =
    section("Non-merged").querySelector<HTMLInputElement>(
      'input[type="text"]',
    )!;
  await act(async () => {
    draft.value = link;
    draft.dispatchEvent(new Event("input", { bubbles: true }));
    draft.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(section("Non-merged").textContent).toContain("Hidden from members");
  expect(section("Non-merged").textContent).toContain(
    "Add a base link to show this variant to members.",
  );
  await act(async () =>
    root.render(
      <Sample
        document={{ ...doc, base_status: { Merged: true, "Non-merged": true } }}
      />,
    ),
  );
  expect(section("Non-merged").textContent).toContain("Shown to members");
});
it.each([true, false])(
  "renders the server's single Base group below TH16 (base edit permission %s)",
  async (editable) => {
    const doc = documentFor(!editable, editable);
    doc.label = "Town Hall 12";
    doc.level = 12;
    doc.fields = doc.fields
      .filter((field) => !field.key.startsWith("bases.non_merged."))
      .map((field) => ({
        ...field,
        group: field.group === "Merged" ? "Base" : field.group,
      }));
    doc.section_readonly = {
      "Town Hall": editable,
      "Base images": !editable,
      Base: !editable,
    };
    doc.base_status = { Base: false };
    await act(async () => root.render(<Sample document={doc} />));
    expect(
      [...host.querySelectorAll(".manage-field-group > legend")].map(
        (node) => node.firstChild?.textContent,
      ),
    ).toEqual(["Town Hall", "Base images", "Base"]);
    expect(host.textContent).not.toMatch(/Merged|Non-merged|this variant/);
    expect(section("Base").textContent).toContain("Hidden from members");
    expect(section("Base").textContent).toContain(
      "Add a base link to show this base to members.",
    );
    expect(!!section("Base").querySelector("input")).toBe(editable);
  },
);
it("base-only users see Town Hall text, not disabled admin inputs or raw IDs", async () => {
  await act(async () =>
    root.render(<Sample document={documentFor(false, true)} />),
  );
  expect(
    section("Town Hall").querySelector("input,select,textarea,button"),
  ).toBeNull();
  expect(section("Town Hall").textContent).toContain("181k – 190k");
  expect(section("Town Hall").textContent).toContain(
    "Only server admins can change the emoji and weight.",
  );
  expect(host.textContent).not.toMatch(/123456789012345678|<:/);
  expect(section("Merged").querySelector("input")).toBeTruthy();
});
it("admin-only users see base text, links and previews with no base editing controls", async () => {
  await act(async () =>
    root.render(<Sample document={documentFor(true, false)} />),
  );
  for (const name of ["Base images", "Merged", "Non-merged"])
    expect(
      section(name).querySelector("input,textarea,button,select"),
    ).toBeNull();
  expect(section("Merged").querySelector("a")?.getAttribute("href")).toBe(link);
  expect(section("Merged").textContent).toContain(
    "Only base managers can change bases.",
  );
  expect(section("Town Hall").querySelector("input")).toBeTruthy();
});
it("upload changes only the image draft and a failed preview becomes muted text", async () => {
  await act(async () => root.render(<Sample document={documentFor()} />));
  const file = new File([new Uint8Array([1, 2, 3])], "sample.png", {
    type: "image/png",
  });
  const upload =
    section("Base images").querySelector<HTMLInputElement>(
      'input[type="file"]',
    )!;
  Object.defineProperty(upload, "files", { value: [file] });
  await act(async () =>
    upload.dispatchEvent(new Event("change", { bubbles: true })),
  );
  expect(apiUpload).toHaveBeenCalledTimes(1);
  expect(vi.mocked(apiUpload).mock.calls[0][0]).toBe(
    "/manage/town-halls/19/upload/war_image?revision=7",
  );
  expect(api).not.toHaveBeenCalled();
  expect(input("War base image").value).toBe(
    "https://images.example/uploaded.jpg",
  );
  const image = section("Base images").querySelector("img")!;
  await act(async () => image.dispatchEvent(new Event("error")));
  expect(section("Base images").textContent).toContain("Image could not load.");
});
