export function filterChannels<T extends { id: string; name: string }>(
  channels: T[],
  query: string,
): T[] {
  const term = query.trim().replace(/^#/, "").toLocaleLowerCase();
  return term
    ? channels.filter(
        (channel) =>
          channel.name.toLocaleLowerCase().includes(term) ||
          channel.id.includes(term),
      )
    : channels;
}
