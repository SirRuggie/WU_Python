import { describe, expect, it } from 'vitest';
import { deliveryExplanation, deliveryLabel, deliveryTime } from './announcementDelivery';

describe('announcement delivery feedback', () => {
  it('never presents queued or uncertain work as delivered', () => {
    expect(deliveryLabel('pending')).toBe('Queued');
    expect(deliveryExplanation('sending')).toContain('not confirmed');
    expect(deliveryLabel('uncertain')).toBe('Needs delivery review');
    expect(deliveryExplanation('uncertain')).toContain('Automatic resend is blocked');
    expect(deliveryLabel()).toBe('Not sent');
  });
  it('distinguishes delivery time from status time and rejects invalid timestamps', () => {
    expect(deliveryTime({ status: 'pending', updated_at: '2026-10-22T12:00:00Z' })).toMatch(/^Status updated /);
    expect(deliveryTime({ status: 'sent', sent_at: '2026-10-22T12:00:00Z' })).toMatch(/^Sent /);
    expect(deliveryTime({ status: 'uncertain', updated_at: 'bad' })).toBeNull();
    expect(deliveryTime(null)).toBeNull();
  });
});
