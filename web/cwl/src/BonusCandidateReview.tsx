import { useEffect, useRef, useState } from 'react';
import type { RaffleAccount } from './bonusRaffle';

export const LAZY_FLAGS = [
  { id: 'missed_sync', label: 'Missed sync', description: 'Account missed the clan sync during CWL.' },
  { id: 'lingering', label: 'Lingering', description: 'Account stayed after it should have moved.' },
  { id: 'left_family', label: 'Left family', description: 'Account left the family during this CWL month.' },
] as const;

type Props = {
  account: RaffleAccount;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onDirty: (dirty: boolean) => void;
  onSave: (flags: string[], overrideReason: string) => Promise<boolean>;
  onRemove?: () => Promise<void>;
};

export default function BonusCandidateReview({ account, busy, error, onCancel, onDirty, onSave, onRemove }: Props) {
  const savedFlags = account.bonus_review?.flags || [];
  const savedReason = account.bonus_review?.override_reason || '';
  const [flags, setFlags] = useState<string[]>(savedFlags);
  const [reason, setReason] = useState(savedReason);
  const heading = useRef<HTMLHeadingElement>(null);
  const dirty = flags.slice().sort().join('|') !== savedFlags.slice().sort().join('|') || reason !== savedReason;

  useEffect(() => { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView({ block: 'nearest' }); }, [account.tag]);
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);

  return (
    <section className="bonus-review-editor" aria-label={`Review ${account.player_name}`}>
      <div className="bonus-editor-heading">
        <div><h3 ref={heading} tabIndex={-1}>Review {account.player_name}</h3><small>{account.tag}</small></div>
        <button type="button" disabled={busy} onClick={onCancel}>Close</button>
      </div>
      <div className="bonus-review-context">
        {account.exclusion && <p><strong>Current exclusion:</strong> {account.exclusion}</p>}
        {account.three_cycle_cooldown && <p><strong>One-season sit-out:</strong> Bonus approved in each of the preceding three CWL seasons{account.cooldown_cycles?.length ? ` (${account.cooldown_cycles.join(', ')})` : ''}.</p>}
        {account.manual_candidate_reason && <p><strong>Added by staff:</strong> {account.manual_candidate_reason}</p>}
        {account.bonus_review?.updated_at && <p className="bonus-review-attribution">Last review saved {new Date(account.bonus_review.updated_at).toLocaleString()}{account.bonus_review.updated_by ? ` by Discord ID ${account.bonus_review.updated_by}` : ''}.</p>}
      </div>
      <p>Mark issues from this CWL month. These flags normally exclude the account from the draw.</p>
      <fieldset disabled={busy}>
        <legend>Season flags</legend>
        {LAZY_FLAGS.map(flag => (
          <label key={flag.id} className="bonus-flag">
            <input type="checkbox" checked={flags.includes(flag.id)} onChange={event => {
              setFlags(current => event.target.checked ? [...current, flag.id] : current.filter(value => value !== flag.id));
            }} />
            <span><strong>{flag.label}</strong><small>{flag.description}</small></span>
          </label>
        ))}
      </fieldset>
      <label className="bonus-override-reason">
        Include by staff exception
        <textarea value={reason} maxLength={500} disabled={busy} onChange={event => setReason(event.target.value)} placeholder="Leave blank to follow the automatic rules; enter a reason to override exclusion" />
      </label>
      {reason.trim() && <p className="bonus-caution">This account can enter the draw despite an automatic rule or flag. The reason is saved with the review.</p>}
      {error && <p className="notice error" role="alert">{error}</p>}
      <div className="bonus-editor-actions">
        {onRemove && <button type="button" className="bonus-remove-candidate" disabled={busy} onClick={() => void onRemove()}>Remove candidate</button>}
        <button type="button" disabled={busy} onClick={onCancel}>Cancel</button>
        <button type="button" className="primary" disabled={busy || !dirty || (!!reason && !reason.trim())} onClick={() => void onSave(flags, reason.trim())}>Save review</button>
      </div>
    </section>
  );
}
