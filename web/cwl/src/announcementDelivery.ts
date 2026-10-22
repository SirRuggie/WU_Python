import type { ManageDelivery } from './manageBridge';

export function deliveryLabel(status?: ManageDelivery['status']): string {
  if (!status) return 'Not sent';
  return {
    pending: 'Queued', sending: 'Sending', sent: 'Sent',
    failed: 'Failed', uncertain: 'Needs delivery review', stale: 'Settings changed',
  }[status] || 'Unknown delivery status';
}

export function deliveryExplanation(status?: ManageDelivery['status']): string {
  if (!status) return 'Review the message before sending.';
  return {
    pending: 'Waiting for the bot. Delivery is not confirmed.',
    sending: 'The bot is sending. Delivery is not confirmed.',
    sent: 'Recorded as delivered. This pool will not send again for this month.',
    failed: 'Delivery failed. Review the error before retrying.',
    uncertain: 'Check Discord first. Automatic resend is blocked.',
    stale: 'Review the changed settings and published roster before retrying.',
  }[status] || 'Refresh status before taking action.';
}

export function deliveryTime(delivery?: ManageDelivery | null): string | null {
  const stamp = delivery?.sent_at || delivery?.updated_at || delivery?.requested_at;
  if (!stamp || !Number.isFinite(Date.parse(stamp))) return null;
  const label = delivery?.sent_at ? 'Sent' : delivery?.updated_at ? 'Status updated' : 'First requested';
  return `${label} ${new Date(stamp).toLocaleString()}`;
}
