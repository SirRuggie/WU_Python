import type { ManageDelivery } from "./manageBridge";
import type { PublicationDraft } from "./publication";
import { publicationDate, hiddenPublicationStatus } from "./publicationStatus";
export function announcementPublicationStatus(
  publication:
    | Pick<PublicationDraft, "published" | "last_publication">
    | undefined,
): string {
  if (!publication) return "Checking publication status…";
  if (publication.published)
    return `Members see roster version ${publication.published.version} · Published ${publicationDate(publication.published.published_at)}`;
  if (publication.last_publication?.withdrawn_at)
    return hiddenPublicationStatus(publication.last_publication);
  return "Publish the roster before announcing";
}
export function announcementDeliveryStatus(
  delivery: ManageDelivery | null | undefined,
  publishedVersion: number | null,
): string {
  if (!delivery) return "Not announced yet";
  switch (delivery.status) {
    case "pending":
      return "Queued · waiting for the bot";
    case "sending":
      return "Sending…";
    case "failed":
      return `Failed · ${delivery.error || "Delivery failed"}`;
    case "uncertain":
      return "Check Discord first: it may have posted. Resending is blocked.";
    case "stale":
      return "Message settings changed since it was queued · review and retry";
    case "sent": {
      const stamp = delivery.sent_at || delivery.updated_at;
      const date =
        stamp && Number.isFinite(Date.parse(stamp))
          ? ` ${publicationDate(stamp)}`
          : "";
      const older =
        delivery.publication_version != null &&
        publishedVersion != null &&
        delivery.publication_version < publishedVersion;
      return `Sent${date}${older ? ` for version ${delivery.publication_version} · Members now see version ${publishedVersion} through the roster link. Announcements aren't resent.` : ""}`;
    }
  }
}
