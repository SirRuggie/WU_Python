export type BankBase = {
  key: string;
  town_hall: number;
  variant: "merged" | "non-merged";
  link: string | null;
  war_base_image: string | null;
  has_details: boolean;
};
export function baseLink(value: string | null): string | null {
  if (!value || /\s/.test(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      url.hostname === "link.clashofclans.com" &&
      !url.username &&
      !url.password &&
      !url.port &&
      !url.hash &&
      url.searchParams.getAll("action").join() === "OpenLayout" &&
      !!url.searchParams.get("id")
      ? value
      : null;
  } catch {
    return null;
  }
}
export function defaultTownHall(
  bases: BankBase[],
  linked: (number | null)[] | null,
): number | null {
  const available = [...new Set(bases.map((b) => b.town_hall))].sort(
    (a, b) => b - a,
  );
  return available.find((th) => linked?.includes(th)) ?? available[0] ?? null;
}
export function variantLabel(base: BankBase) {
  return base.variant === "merged" ? "Merged defenses" : "Non-merged defenses";
}
