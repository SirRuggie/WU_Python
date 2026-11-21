import { expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ManagementEditorForm from "./ManagementEditorForm";
import type { ManagementDocument } from "./serverManagement";

const document: ManagementDocument = {
  id: "gauntlet--family-particulars",
  label: "Family Particulars",
  description: "",
  group: "Welcome messages",
  revision: 5,
  fields: [
    {
      key: "sections.28",
      label: "Heading",
      group: "How Our Clans Work",
      type: "textarea",
      value: "Start heading",
    },
    {
      key: "sections.29",
      label: "Intro",
      group: "How Our Clans Work",
      type: "textarea",
      value: "Intro text",
    },
    {
      key: "sections.30",
      label: "Heading",
      group: "Every Day",
      type: "textarea",
      value: "Every Day heading",
    },
    {
      key: "sections.5",
      label: "Friendly Challenges",
      group: "Every Day",
      type: "textarea",
      value: "Challenges text",
    },
    {
      key: "sections.8",
      label: "Clan Games",
      group: "Every Day",
      type: "textarea",
      value: "Games text",
    },
    {
      key: "media.welcome",
      label: "Welcome banner",
      group: "Images",
      type: "text",
      value: "https://example.com/banner.png",
    },
  ],
};
function render(doc = document, fieldPage = 0) {
  const noop = vi.fn();
  return renderToStaticMarkup(
    <ManagementEditorForm
      selected={doc}
      document={doc}
      draft={Object.fromEntries(
        doc.fields.map((field) => [field.key, field.value]),
      )}
      busy={false}
      dirty={false}
      conflict={false}
      publishDirty={false}
      statusUrl=""
      fieldPage={fieldPage}
      compactPreview={false}
      operationsWorkspace={false}
      onSave={noop}
      onOpenSharedRules={noop}
      setFieldPage={noop}
      setMobilePane={noop}
      setDocument={noop}
      setDraft={noop}
      setNotice={noop}
    />,
  );
}
it("shows box names in post order then Images, and only the selected box fields", () => {
  const html = render(document, 1);
  expect(html).toContain("Message or setting to edit");
  expect(html).toMatch(
    /How Our Clans Work<\/option>.*Every Day<\/option>.*Images<\/option>/,
  );
  expect(html).toContain("Challenges text");
  expect(html).toContain("Games text");
  expect(html).not.toContain("Intro text");
  expect(html).not.toContain("https://example.com/banner.png");
});
it("shared Rules stays read-only with an explicit shared-editor action", () => {
  const html = render({
    ...document,
    id: "gauntlet--wu-faq",
    fields: [
      {
        key: "shared_rules.0",
        label: "Heading",
        group: "Family Rules",
        type: "textarea",
        value: "Shared heading",
        readonly: true,
      },
      {
        key: "shared_rules.1",
        label: "Body",
        group: "Family Rules",
        type: "textarea",
        value: "Shared rules",
        readonly: true,
      },
    ],
  });
  expect(html).toContain("Shared rules");
  expect(html).toContain("Edit shared Family Rules");
  expect(html).toContain("disabled");
});
