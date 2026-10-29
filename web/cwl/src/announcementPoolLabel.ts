import type { Pool } from "./api";
export const announcementPoolLabel = (pool: Pool) =>
  pool === "main" ? "Main CWL" : "Lazy CWL";
