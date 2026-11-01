export type Profile = {
  zone_id: string;
  gmt_label: string;
  utc_offset_minutes: number;
  country: string | null;
  flag: string | null;
  name_source_tag: string | null;
  source: string;
  revision: number;
};
export type Member = {
  discord_id: string;
  name: string;
  nickname: string | null;
  bot: boolean;
  status: string;
  profile: Profile | null;
  parsed: { label: string; offsetMinutes: number | null } | null;
  skip_reason: string | null;
};
export type Directory = {
  members: Member[];
  countries: {
    code: string;
    label: string;
    flag: string;
    zone_id?: string | null;
  }[];
  zones: { id: string; label: string }[];
  permission: string;
};
export type Change = {
  discord_id: string;
  name?: string;
  old_nickname: string | null;
  new_nickname: string | null;
  revision: number;
  skip_reason?: string | null;
  status?: string;
  message?: string;
};
export type Run = { run_id: string; state: string; rows: Change[] };
export type RequestState = {
  request_id: string;
  status: string;
  status_url: string;
  message: string;
  result?: { message?: string; counts?: Record<string, number> };
};
