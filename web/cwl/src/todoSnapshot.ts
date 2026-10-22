import type { TodoSnapshot } from './todo'

/** Keep the existing warm view for other tasks, never persist Clan Games scores. */
export function withoutGamesScores(snapshot: TodoSnapshot): TodoSnapshot {
  return { ...snapshot, views: { ...snapshot.views, games: {
    ok: true, note: 'Checking this event’s Clan Games scores…', notes: [],
    unavailable: '', incomplete: '', rows: [],
  } } }
}
