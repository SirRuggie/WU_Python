import type { DeclarationExtraResponse } from "./declarationExtras";
import type { FillerSaveResult } from "./RosterFillerCheckbox";
export function patchDeclarationMark(
  data: DeclarationExtraResponse,
  saved: FillerSaveResult,
) {
  return patchDeclarationMarks(data, [saved]);
}

export function patchDeclarationMarks(
  data: DeclarationExtraResponse,
  saves: FillerSaveResult[],
) {
  const marks = new Map(
    saves
      .filter((saved) => saved.tag && typeof saved.roster_filler === "boolean")
      .map((saved) => [saved.tag!, saved]),
  );
  if (!marks.size) return data;
  return {
    ...data,
    revision: Math.max(
      data.revision || 0,
      ...saves.map((saved) => saved.revision),
    ),
    clans: data.clans.map((clan) => {
      if (clan.status !== "current") return clan;
      const members = new Map(
        [
          ...(clan.extras || []),
          ...(clan.low_th || []),
          ...(clan.fillers || []),
          ...(clan.unpublished || []),
        ].map((m) => [m.tag, m]),
      );
      for (const [tag, saved] of marks) {
        const old = members.get(tag);
        if (old)
          members.set(tag, {
            ...old,
            roster_filler: saved.roster_filler,
            roster_filler_revision: saved.mark_revision,
          });
      }
      const rows = [...members.values()].sort(
        (a, b) => a.name.localeCompare(b.name) || a.tag.localeCompare(b.tag),
      );
      const low = (th: number | null) =>
        typeof th === "number" && th > 0 && th <= 9;
      const extras = rows.filter(
        (m) =>
          !m.assigned_here &&
          !m.not_published_yet &&
          !m.roster_filler &&
          !low(m.town_hall),
      );
      return {
        ...clan,
        extras,
        count: extras.length,
        unpublished: rows.filter((m) => m.not_published_yet === true),
        unpublished_count: rows.filter((m) => m.not_published_yet === true)
          .length,
        low_th: rows.filter((m) => low(m.town_hall)),
        fillers: rows.filter((m) => m.roster_filler),
      };
    }),
  };
}
