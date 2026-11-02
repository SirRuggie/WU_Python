import { api, ApiError } from "./api";
import type { FillerSaveResult } from "./RosterFillerCheckbox";

export type FillerRow = {
  tag: string;
  name: string;
  value: boolean;
  markRevision: number;
};
type State = FillerRow & { saved: boolean; pending: boolean };
type Save = (
  path: string,
  method: string,
  body: unknown,
  options?: { signal: AbortSignal },
) => Promise<FillerSaveResult>;

/** One page's explicit tap intents. No retry, polling or post-unmount draining. */
export class FillerMarkQueue {
  private rows = new Map<string, State>();
  private waiting: string[] = [];
  private active = "";
  private activeController: AbortController | null = null;
  private running = false;
  private writeBusy = false;
  lastSaved: FillerSaveResult | null = null;
  private disposed = false;
  private listeners = new Set<() => void>();
  private version = 0;
  private revision: number;
  private confirmed: FillerSaveResult[] = [];
  private flush: (saved: FillerSaveResult[]) => void = () => {};
  private accessLost: () => void = () => {};
  blocked = false;
  private externallyDisabled = false;
  notSaved: FillerRow[] = [];
  unknownOutcome = false;

  constructor(
    readonly seasonId: string,
    revision: number,
    private save: Save = api,
  ) {
    this.revision = revision;
  }
  configure(
    flush: (saved: FillerSaveResult[]) => void,
    accessLost: () => void,
  ) {
    this.flush = flush;
    this.accessLost = accessLost;
  }
  get working() {
    return (
      !this.disposed &&
      (this.running || this.waiting.length > 0 || this.writeBusy)
    );
  }
  get disabled() {
    return (
      this.disposed || this.blocked || this.externallyDisabled || this.writeBusy
    );
  }
  setDisabled(disabled: boolean) {
    if (this.externallyDisabled !== disabled) {
      this.externallyDisabled = disabled;
      this.emit();
    }
  }
  get latestRevision() {
    return this.revision;
  }
  setWriteBusy(busy: boolean) {
    this.writeBusy = busy;
    this.emit();
  }
  clearUndo() {
    this.lastSaved = null;
    this.emit();
  }
  syncRevision(revision: number) {
    this.revision = Math.max(this.revision, revision);
  }
  snapshot = () => this.version;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private emit() {
    this.version++;
    this.listeners.forEach((listener) => listener());
  }
  row(tag: string) {
    return this.rows.get(tag);
  }
  enqueue(input: FillerRow, value: boolean) {
    if (this.disabled) return;
    const row = this.rows.get(input.tag) || {
      ...input,
      saved: input.value,
      pending: false,
    };
    row.name = input.name;
    row.value = value;
    this.rows.set(input.tag, row);
    // Replace an unsent same-row intent at its newest tap position.
    this.waiting = this.waiting.filter((tag) => tag !== input.tag);
    if (this.active === input.tag || row.saved !== value)
      this.waiting.push(input.tag);
    row.pending = this.active === input.tag || row.saved !== value;
    this.emit();
    queueMicrotask(() => {
      void this.drain();
    });
  }
  observeRows(rows: FillerRow[]) {
    if (this.working || this.blocked || this.disposed) return;
    let changed = false;
    for (const input of rows) {
      const old = this.rows.get(input.tag);
      if (old && old.markRevision > input.markRevision) continue;
      if (
        !old ||
        old.saved !== input.value ||
        old.markRevision !== input.markRevision ||
        old.name !== input.name
      ) {
        this.rows.set(input.tag, {
          ...input,
          saved: input.value,
          pending: false,
        });
        changed = true;
      }
    }
    if (changed) this.emit();
  }
  /** Only an explicit successful page read may clear a halted queue. */
  refreshed(revision: number) {
    if (this.working || this.disposed) return;
    this.revision = revision;
    this.rows.clear();
    this.blocked = false;
    this.notSaved = [];
    this.unknownOutcome = false;
    this.emit();
  }
  activate() {
    this.disposed = false;
    this.emit();
  }
  acceptExternal(saved: FillerSaveResult) {
    if (this.running || this.waiting.length || this.disposed) return;
    this.lastSaved = null;
    this.syncRevision(saved.revision);
    if (
      saved.tag &&
      typeof saved.roster_filler === "boolean" &&
      typeof saved.mark_revision === "number"
    ) {
      this.rows.set(saved.tag, {
        tag: saved.tag,
        name: this.rows.get(saved.tag)?.name || saved.tag,
        value: saved.roster_filler,
        saved: saved.roster_filler,
        markRevision: saved.mark_revision,
        pending: false,
      });
    }
    this.emit();
  }
  dispose() {
    this.disposed = true;
    this.waiting = [];
    this.activeController?.abort();
    this.emit();
    this.listeners.clear();
  }
  private async drain() {
    if (
      this.running ||
      this.disposed ||
      this.blocked ||
      this.writeBusy ||
      !this.waiting.length
    )
      return;
    this.running = true;
    this.emit();
    let denied = false;
    try {
      while (this.waiting.length && !this.disposed) {
        const tag = this.waiting.shift()!;
        const row = this.rows.get(tag)!;
        const target = row.value;
        if (target === row.saved) {
          row.pending = false;
          continue;
        }
        this.active = tag;
        row.pending = true;
        this.emit();
        try {
          const sentRevision = this.revision;
          const controller = new AbortController();
          this.activeController = controller;
          let timer: ReturnType<typeof setTimeout> | undefined;
          let saved: FillerSaveResult;
          try {
            saved = await Promise.race([
              this.save(
                `/seasons/${encodeURIComponent(this.seasonId)}/roster-filler/${encodeURIComponent(tag)}`,
                "PATCH",
                {
                  revision: this.revision,
                  roster_filler: target,
                  mark_revision: row.markRevision,
                },
                { signal: controller.signal },
              ),
              new Promise<never>((_, reject) => {
                timer = setTimeout(() => {
                  controller.abort();
                  reject(new DOMException("Save timed out", "TimeoutError"));
                }, 45000);
              }),
            ]);
          } finally {
            clearTimeout(timer);
            this.activeController = null;
          }
          if (this.disposed) return;
          if (
            !Number.isInteger(saved.revision) ||
            saved.revision < sentRevision ||
            !Number.isInteger(saved.mark_revision) ||
            saved.mark_revision! < 0 ||
            saved.roster_filler !== target ||
            (saved.tag !== undefined && saved.tag !== tag)
          ) {
            throw new Error("Save response could not be confirmed");
          }
          this.revision = Math.max(this.revision, saved.revision);
          row.saved = target;
          row.markRevision = saved.mark_revision!;
          row.pending = row.value !== row.saved;
          this.lastSaved = { ...saved, tag };
          this.confirmed.push(this.lastSaved);
          if (row.pending && !this.waiting.includes(tag))
            this.waiting.push(tag);
          this.active = "";
          this.emit();
        } catch (cause) {
          if (this.disposed) return;
          denied =
            cause instanceof ApiError && [401, 403].includes(cause.status);
          this.unknownOutcome =
            !(cause instanceof ApiError) ||
            cause.status === 0 ||
            cause.status >= 500;
          const unsaved = [...new Set([tag, ...this.waiting])];
          this.notSaved = unsaved.map((key) => ({ ...this.rows.get(key)! }));
          this.rows.forEach((item) => {
            item.value = item.saved;
            item.pending = false;
          });
          this.waiting = [];
          this.blocked = true;
          this.active = "";
          break;
        }
      }
    } finally {
      this.running = false;
      if (!this.disposed) {
        const saved = this.confirmed.splice(0);
        if (saved.length) this.flush(saved);
        this.emit();
        if (denied) this.accessLost();
      }
    }
  }
}
