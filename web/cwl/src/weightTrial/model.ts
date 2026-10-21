export type Member = {
  tag: string;
  name: string;
  town_hall: number | null;
  weight: number | null;
  revision: number;
};
export type Roster = {
  clan: { tag: string; name: string };
  members: Member[];
  checked_at: string;
};
export const weightText = (weight: number | null) =>
  weight === null ? "" : String(weight / 1000);
export function parseWeight(text: string): number | null {
  const value = text.trim();
  if (!value) return null;
  if (!/^[0-9]{1,3}$/.test(value) || Number(value) < 1)
    throw new Error("Use whole numbers from 1 to 999. Example: 149 = 149,000.");
  return Number(value) * 1000;
}
export function pasteWeights(text: string, available: number): string[] {
  const values = text.replace(/\r/g, "").replace(/\n$/, "").split("\n");
  if (values.length > available)
    throw new Error("There are more pasted weights than remaining members.");
  for (const value of values) parseWeight(value);
  return values.map((value) => value.trim());
}
export function copyRows(rows: Member[], values: Record<string, string>) {
  const safe = (value: string) =>
    /^[=+@\-\t\r\n]/.test(value.trimStart())
      ? "'" + value.replace(/[\t\r\n]/g, " ")
      : value.replace(/[\t\r\n]/g, " ");
  return [
    "Player tag\tPlayer name\tTown Hall\tWeight (k)",
    ...rows.map((row) =>
      [
        row.tag,
        safe(row.name),
        row.town_hall ?? "",
        values[row.tag] ?? "",
      ].join("\t"),
    ),
  ].join("\n");
}
