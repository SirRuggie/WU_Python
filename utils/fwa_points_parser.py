"""Parser for a points.fwafarm.com clan page.

Pure and dependency-light so it can be unit-tested against saved HTML with no
network call. The only hard requirement is the Win Calculator block; if that or
the opponent tag cannot be found, we raise so the caller can fail soft.
"""

import re
from bs4 import BeautifulSoup


class FwaPointsParseError(Exception):
    """Raised when the page has no usable Win Calculator block."""


def sanitize_tag(raw: str) -> str:
    """Normalize a Clash of Clans tag: drop '#', uppercase, keep only [0-9A-Z]."""
    if not raw:
        return ""
    return re.sub(r"[^0-9A-Z]", "", raw.upper())


def _field_after_bold(soup, label: str):
    """Return the text right after <b>label</b>, up to the next tag."""
    for b in soup.find_all("b"):
        if b.get_text(strip=True).rstrip(":") == label:
            nxt = b.next_sibling
            if nxt is not None:
                return str(nxt).lstrip(":").strip()
    return None


def parse_clan_points(html: str, our_tag: str) -> dict:
    """Extract the Win Calculator fields for the clan we scraped for.

    `our_tag` is the tag we requested; the opponent is the clan link in the box
    that is not ours. Raises FwaPointsParseError if the block is missing.
    """
    our_tag = sanitize_tag(our_tag)
    soup = BeautifulSoup(html, "html.parser")

    box = soup.select_one("p.winner-box")
    if box is None:
        raise FwaPointsParseError("winner-box not found")

    box_tags = []
    for a in box.find_all("a", href=True):
        m = re.search(r"clan\?tag=([0-9A-Za-z]+)", a["href"])
        if m:
            box_tags.append(sanitize_tag(m.group(1)))
    if len(box_tags) < 2:
        raise FwaPointsParseError(f"expected two clan tags in winner-box, got {box_tags}")

    others = [t for t in box_tags if t != our_tag]
    opponent_tag = others[0] if others else box_tags[1]

    box_text = box.get_text(" ", strip=True)

    war_number = None
    war_link = box.find("a", href=re.compile(r"/war\?id="))
    if war_link:
        m = re.search(r"id=(\d+)", war_link["href"])
        if m:
            war_number = int(m.group(1))
    if war_number is None:
        m = re.search(r"War #(\d+)", box_text)
        war_number = int(m.group(1)) if m else None

    m = re.search(r"Sync #(\d+)", box_text)
    sync_number = int(m.group(1)) if m else None

    m = re.search(r"vs\.\s*(.+?)\s*\(\s*" + re.escape(opponent_tag), box_text, re.IGNORECASE)
    opponent_name = m.group(1).strip() if m else None

    # Verdict = the last line of the box (after the final <br>), tags stripped.
    segments = re.split(r"<br\s*/?>", box.decode_contents(), flags=re.IGNORECASE)
    verdict_html = segments[-1] if segments else box.decode_contents()
    raw_verdict = BeautifulSoup(verdict_html, "html.parser").get_text().strip()

    point_balance = None
    pb = _field_after_bold(soup, "Point Balance")
    if pb is not None:
        try:
            point_balance = int(pb)
        except ValueError:
            point_balance = None

    active_raw = _field_after_bold(soup, "Active FWA")
    active_fwa = (active_raw or "").strip().lower() == "yes"

    return {
        "clan_name": _field_after_bold(soup, "Clan Name"),
        "point_balance": point_balance,
        "active_fwa": active_fwa,
        "war_number": war_number,
        "sync_number": sync_number,
        "opponent_tag": opponent_tag,
        "opponent_name": opponent_name,
        "raw_verdict": raw_verdict,
        "last_war_state": _field_after_bold(soup, "Last Known War State"),
        "clan_tags_in_box": box_tags,
    }


def is_newer_war(prev_record, parsed) -> bool:
    """True if the scraped page shows a war newer than the one already stored.

    Guards against writing a stale PREVIOUS-war verdict when the new war is against
    the SAME opponent tag (tag alone cannot tell them apart). A genuinely new FWA
    war always has a higher, monotonically increasing war number.
    """
    prev_wn = (prev_record or {}).get("war_number")
    wn = parsed.get("war_number")
    if prev_wn is None:
        return True          # no reliable prior war to compare -> first catch
    if wn is None:
        return False         # cannot confirm the page advanced -> keep waiting
    return wn > prev_wn
