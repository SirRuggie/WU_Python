/** Mobile keyboard behavior for searches and exact identifiers; never prose. */
export const identifierInputProps = {
  autoCapitalize: "none",
  autoCorrect: "off",
  spellCheck: false,
} as const;

export const searchInputProps = {
  ...identifierInputProps,
  enterKeyHint: "search",
} as const;

export const numericInputProps = { inputMode: "numeric" } as const;

/** Shared Input users inherit behavior from their existing HTML type. */
export function mobileInputProps(type?: string) {
  return type === "search"
    ? searchInputProps
    : type === "number"
      ? numericInputProps
      : {};
}
