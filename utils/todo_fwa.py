"""Shared Discord/web Todo FWA records and current-war matching."""
from datetime import datetime
from utils import todo_data
from utils.fwa_blacklist import blacklisted_tags
from utils.fwa_points_parser import sanitize_tag


def matching_outcome(row, records):
    record = records.get(row.clan_tag) if records else None
    if not record or row.ends_at is None:
        return None
    try:
        end = todo_data._utc_epoch(datetime.fromisoformat(record.get('coc_war_end_time')))
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if end is None or abs(end - row.ends_at) > 60:
        return None
    status = 'blacklisted' if record.get('opponent_blacklisted') else record.get('our_outcome')
    return {'status': status if status in ('win', 'lose', 'blacklisted') else 'unknown',
            'opponent': str(record.get('coc_opponent_name') or record.get('opponent_name') or '')[:150]}


async def load_fwa_records(mongo, war_rows: list, *, strict=False) -> dict:
    """{Row.clan_tag: fwa_points record} for the distinct clans in the War view.

    One batched find() covers every clan at once. fwa_points documents are
    keyed by the sanitized tag (no '#'), while Row.clan_tag carries whatever
    format the CoC API returned, so results are re-keyed back to that original
    form for a direct row.clan_tag lookup at render time.
    """
    if mongo is None:
        return {}
    sanitized_to_original: dict[str, str] = {}
    for row in war_rows:
        if not row.clan_tag:
            continue
        sanitized = sanitize_tag(row.clan_tag)
        if sanitized:
            sanitized_to_original[sanitized] = row.clan_tag
    if not sanitized_to_original:
        return {}
    try:
        docs = await mongo.fwa_points.find(
            {"_id": {"$in": list(sanitized_to_original)}}
        ).to_list(length=None)
    except Exception as exc:  # noqa: BLE001 - a missing suffix must not break the panel
        if strict:
            raise
        print(f"[todo] fwa_points lookup failed: {type(exc).__name__}: {exc}")
        return {}
    records = {
        sanitized_to_original[doc["_id"]]: doc
        for doc in docs
        if doc.get("_id") in sanitized_to_original
    }

    # Re-checked against the blacklist on every load (not just what the
    # scraper saw at the time) so a clan blacklisted after the record was
    # scraped still shows as blacklisted here.
    opponent_tags = {
        sanitize_tag(doc.get("scraped_opponent_tag") or "") for doc in records.values()
    }
    opponent_tags.discard("")
    if opponent_tags:
        try:
            blacklisted = await blacklisted_tags(mongo, opponent_tags)
        except Exception as exc:  # noqa: BLE001 - a missing suffix must not break the panel
            if strict:
                raise
            print(f"[todo] fwa_blacklist lookup failed: {type(exc).__name__}: {exc}")
            blacklisted = set()
        for doc in records.values():
            opp_tag = sanitize_tag(doc.get("scraped_opponent_tag") or "")
            if opp_tag:
                doc["opponent_blacklisted"] = opp_tag in blacklisted

    return records
