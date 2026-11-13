import { api } from "./api";
import type { ManagementField, ManagementSection } from "./serverManagement";

export const apiPath = (path: string) => path.replace(/^\/api\/cwl(?=\/)/, "");
export const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Could not load settings. Try again.";
export const sectionEndpoint = (section: ManagementSection) =>
  apiPath(section.endpoint || `/manage/${encodeURIComponent(section.id)}`);

export async function hydrateFields(fields: ManagementField[]) {
  if (
    !fields.some(
      (field) =>
        (field.source === "roles" ||
          field.source === "channels" ||
          ["channel", "role", "multiselect"].includes(field.type)) &&
        !field.options &&
        field.source !== "members",
    )
  )
    return fields;
  const choices = await api<{
    channels: { value: string; label: string }[];
    roles: { value: string; label: string }[];
  }>("/manage/choices");
  return fields.map((field) =>
    field.options
      ? field
      : {
          ...field,
          options:
            field.source === "members"
              ? []
              : field.type === "channel" || field.source === "channels"
                ? choices.channels
                : field.source === "roles" ||
                    ["role", "multiselect"].includes(field.type)
                  ? choices.roles
                  : undefined,
        },
  );
}
