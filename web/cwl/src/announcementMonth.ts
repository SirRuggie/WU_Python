const months = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
export function announcementMonth(label: string): string {
  const match = label.trim().match(/^([A-Za-z]+) (\d{4})$/);
  if (!match) return "";
  const month = months.findIndex(
    (value) => value.toLowerCase() === match[1].toLowerCase(),
  );
  return month < 0 ? "" : `${match[2]}-${String(month + 1).padStart(2, "0")}`;
}
export function announcementMonthLabel(cycle: string): string {
  const match = cycle.match(/^(\d{4})-(0[1-9]|1[0-2])$/);
  return match ? `${months[Number(match[2]) - 1]} ${match[1]}` : "month";
}
