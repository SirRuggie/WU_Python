import { useState } from 'react'
// Uses the same Discord Town Hall emoji IDs as utils/emoji.py.
const townHallEmoji: Record<number, string> = {
  "2": "1395728426849275997",
  "3": "1395728517299306537",
  "4": "1395728565575618623",
  "5": "1395728620185718796",
  "6": "1395728668583792716",
  "7": "1395728738334806152",
  "8": "1395728783591608360",
  "9": "1395728820471857266",
  "10": "1395728880991735899",
  "11": "1395728917339570186",
  "12": "1395728951854501959",
  "13": "1395728985857458261",
  "14": "1395729011404963843",
  "15": "1395729045962096651",
  "16": "1395729067990319164",
  "17": "1395729126014324837",
  "18": "1447966636496650310"
}
export default function TownHallIcon({ level }: { level: number | null | undefined }) {
  const [failedId, setFailedId] = useState<string | null>(null)
  const id = level == null ? undefined : townHallEmoji[level]
  const label = level == null ? 'Town Hall unknown' : `Town Hall ${level}`
  return id && failedId !== id
    ? <img className="town-hall-icon" src={`https://cdn.discordapp.com/emojis/${id}.png?size=64`} alt={label} title={label} width={32} height={32} onError={() => setFailedId(id)} />
    : <span className="town-hall-fallback" title={label}>TH {level ?? '—'}</span>
}
