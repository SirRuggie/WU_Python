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


def _normalize(text) -> str:
    """Whitespace-collapsed, case-folded text for name comparisons."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def parse_active_fwa(html: str) -> bool | None:
    """Read the standalone `<b>Active FWA</b>: Yes/No` field.

    Deliberately independent of the Win Calculator block: this is used to
    check the OPPONENT's page, which may have no winner-box yet (no war
    detected for them) while still carrying this field. Returns None if the
    label itself is missing.

    points.fwafarm.com answers HTTP 200 with the literal body "Clan not
    found." for a tag it does not recognize - that is not FWA, full stop, so
    it is treated as False rather than falling through to "label missing".
    """
    if (html or "").strip().lower() == "clan not found.":
        return False
    soup = BeautifulSoup(html, "html.parser")
    active_raw = _field_after_bold(soup, "Active FWA")
    if active_raw is None:
        return None
    return active_raw.strip().lower() == "yes"


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

    # The "A (tagA) vs. B (tagB)" line is not always ours-first (the opponent
    # can be listed first on the points site), so names are parsed out of the
    # raw HTML segment rather than assumed to be in a fixed order. That
    # segment sits between the first "<br><br>" and the second, and is
    # identifiable - once the box is split on <br> tags - as the segment
    # ending with "):" . Within it, each clan's name is the text immediately
    # preceding " (<a href=".../clan?tag=TAG">": the first clan's name is
    # measured from the segment start, the second's from just after "vs.".
    box_html = box.decode_contents()
    br_segments = re.split(r"<br\s*/?>", box_html, flags=re.IGNORECASE)
    vs_segment = next((s for s in br_segments if s.strip().endswith("):")), None)

    def _name_before_tag_link(fragment: str, tag: str, start: int = 0):
        found = re.search(
            r"([^(]*)\(\s*<a\b[^>]*\bhref=\"[^\"]*clan\?tag=" + re.escape(tag) + r"\b",
            fragment[start:],
            re.IGNORECASE,
        )
        return found.group(1).strip() if found else None

    name_map = {}
    if vs_segment is not None and len(box_tags) >= 2:
        name_map[box_tags[0]] = _name_before_tag_link(vs_segment, box_tags[0])
        vs_kw = re.search(r"vs\.", vs_segment, re.IGNORECASE)
        vs_pos = vs_kw.end() if vs_kw else 0
        name_map[box_tags[1]] = _name_before_tag_link(vs_segment, box_tags[1], vs_pos)

    opponent_name = name_map.get(opponent_tag)
    our_name_in_box = name_map.get(our_tag)

    # Verdict = the last line of the box (after the final <br>), tags stripped.
    segments = re.split(r"<br\s*/?>", box.decode_contents(), flags=re.IGNORECASE)
    verdict_html = segments[-1] if segments else box.decode_contents()
    verdict_soup = BeautifulSoup(verdict_html, "html.parser")
    raw_verdict = verdict_soup.get_text().strip()

    # The predicted winner is the clan bolded in that last segment, e.g.
    # "<b>Edrag Rush</b> should win by points (10 > 9)".
    winner_tag = verdict_soup.find("b")
    predicted_winner_name = winner_tag.get_text(strip=True) if winner_tag else None

    point_balance = None
    pb = _field_after_bold(soup, "Point Balance")
    if pb is not None:
        try:
            point_balance = int(pb)
        except ValueError:
            point_balance = None

    active_raw = _field_after_bold(soup, "Active FWA")
    active_fwa = (active_raw or "").strip().lower() == "yes"

    clan_name = _field_after_bold(soup, "Clan Name")

    # "win"/"lose" from OUR side: which name the verdict bolded. Neither match
    # (unreadable name, or a draw-shaped verdict) falls back to "unknown"
    # rather than guessing. Both sides of the comparison must be non-empty -
    # an empty `<b></b>` (predicted_winner_name == "") and a missing Clan Name
    # field (clan_name is None, normalizing to "") would otherwise compare
    # equal as two blank strings and produce a false "win".
    predicted_winner_norm = _normalize(predicted_winner_name)
    clan_name_norm = _normalize(clan_name)
    opponent_name_norm = _normalize(opponent_name)
    if predicted_winner_norm and clan_name_norm and predicted_winner_norm == clan_name_norm:
        our_outcome = "win"
    elif predicted_winner_norm and opponent_name_norm and predicted_winner_norm == opponent_name_norm:
        our_outcome = "lose"
    else:
        our_outcome = "unknown"

    return {
        "clan_name": clan_name,
        "point_balance": point_balance,
        "active_fwa": active_fwa,
        "war_number": war_number,
        "sync_number": sync_number,
        "opponent_tag": opponent_tag,
        "opponent_name": opponent_name,
        "our_name_in_box": our_name_in_box,
        "raw_verdict": raw_verdict,
        "predicted_winner_name": predicted_winner_name,
        "our_outcome": our_outcome,
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
