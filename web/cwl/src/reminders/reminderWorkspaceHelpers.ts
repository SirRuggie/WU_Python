export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Request failed. Try again.";
export const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

export type Confirmation = {
  text: string;
  confirmLabel?: string;
  action: () => void;
};
export type Act = (work: () => Promise<void>) => Promise<void>;
