"""Run real screenshots through the production scanner and print the numbers.

The scanner decides everything with thresholds and then throws the measurements
away: `_artwork_identity_mismatches` computes a page's mean hash distance and
its nearest rival, compares them, and returns only card ids. So a page that
missed by two bits and a page that missed by forty look identical from outside.

This calls the production functions unmodified and prints what they measured.
It changes no thresholds and imports nothing from Discord or Mongo.

    py tools/scan_diagnose.py "C:/path/to/screenshots"

Screenshots are read from the directory given; nothing is copied into the repo.
Real captures carry a player name, clan and resource counts, so they are the
member's data and do not belong in git.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from utils import card_scan as cs  # noqa: E402
from utils.cards import CARDS  # noqa: E402

COLUMNS = cs.COLLECTION_COLUMNS
PAGE_SLOTS = COLUMNS * 2
PAGES = len(CARDS) // PAGE_SLOTS


def _page_label(position: int) -> str:
    start = position * PAGE_SLOTS
    window = CARDS[start:start + PAGE_SLOTS]
    return f"{window[0].name} -> {window[-1].name}"


def _page_mean(observed, position: int) -> float | None:
    """Mean Hamming distance of an observed page against catalog position."""
    candidates = CARDS[position * PAGE_SLOTS:][:len(observed)]
    if len(candidates) < len(observed):
        return None
    return sum(
        (fingerprint ^ cs.CARD_ARTWORK_HASHES[card.id]).bit_count()
        for card, fingerprint in zip(candidates, observed)
    ) / len(observed)


def _frame_gate(image, result, position: int):
    """Which slots fail the category-frame hue test, and by how much."""
    start = position * PAGE_SLOTS
    slots = [slot for row in result.rows for slot in row.slots]
    expected = CARDS[start:start + len(slots)]
    if len(slots) != PAGE_SLOTS or len(expected) != len(slots):
        return None
    failures = []
    for index, (slot, card) in enumerate(zip(slots, expected)):
        hue = cs._frame_hue(image, slot.bounds)
        target = cs.CATEGORY_FRAME_HUES.get(card.category)
        if hue is None or target is None:
            failures.append((index, card.name, hue, target, None))
            continue
        delta = cs._hue_distance(hue, target)
        if delta > cs.CATEGORY_FRAME_HUE_TOLERANCE:
            failures.append((index, card.name, hue, target, delta))
    return failures


def diagnose(path: Path) -> dict:
    payload = path.read_bytes()
    report: dict = {"name": path.name, "hashes": {}}

    loaded = cs._load_still(payload)
    if isinstance(loaded, str):
        report["fatal"] = loaded
        return report
    image, source_size = loaded
    report["source_size"] = source_size
    report["scan_size"] = image.size

    components = cs._saturated_components(image)
    card_sized = [
        box for box in components
        if cs._is_card_sized_component(box, cs._bounds_area(box), image.size)
    ]
    report["components"] = len(components)
    report["card_sized"] = len(card_sized)

    clusters = cs._cluster_components_by_row(card_sized)
    report["clusters"] = [len(c) for c in clusters]
    report["six_wide_clusters"] = sum(1 for c in clusters if len(c) == COLUMNS)

    result = cs.scan_visible_rows(payload)
    report["rows_accepted"] = len(result.rows)
    report["warnings"] = list(result.warnings)

    if len(result.rows) != 2:
        report["verdict"] = "REJECTED"
        report["reason"] = (
            f"scanner needs exactly 2 complete rows, found {len(result.rows)}"
        )
        return report

    observed = cs._artwork_hashes_for_rows(image, result.rows)
    report["observed_hashes"] = len(observed) if observed else 0
    if observed:
        for card_index, fingerprint in enumerate(observed):
            report["hashes"][card_index] = fingerprint

    pages = []
    for position in range(PAGES):
        entry = {
            "position": position,
            "label": _page_label(position),
            "frame_failures": _frame_gate(image, result, position),
            "mean": _page_mean(observed, position) if observed else None,
        }
        pages.append(entry)
    report["pages"] = pages

    means = [p["mean"] for p in pages if p["mean"] is not None]
    if means:
        best = min(range(len(pages)), key=lambda i: pages[i]["mean"])
        ordered = sorted(means)
        report["best_page"] = best
        report["best_mean"] = pages[best]["mean"]
        report["rival_mean"] = ordered[1] if len(ordered) > 1 else None
        report["gap"] = (ordered[1] - ordered[0]) if len(ordered) > 1 else None

    accepted = cs._matching_catalog_positions(image, result)
    report["frame_gate_positions"] = list(accepted)
    report["verdict"] = "ACCEPTED" if accepted else "REJECTED"
    return report


def _print(report: dict) -> None:
    print(f"\n{'=' * 72}\n{report['name']}\n{'=' * 72}")
    if "fatal" in report:
        print(f"  FATAL: {report['fatal']}")
        return
    print(f"  source {report['source_size']}  ->  scanned at {report['scan_size']}")
    print(f"  saturated components : {report['components']}")
    print(f"  card-sized           : {report['card_sized']}")
    print(f"  row clusters         : {report['clusters']}"
          f"  (six-wide: {report['six_wide_clusters']})")
    print(f"  rows the scanner took: {report['rows_accepted']}")
    if report["warnings"]:
        print(f"  warnings             : {', '.join(report['warnings'])}")

    if report["rows_accepted"] != 2:
        print(f"\n  VERDICT: {report['verdict']} - {report['reason']}")
        return

    print(f"  artwork hashes read  : {report['observed_hashes']}")
    print("\n  page                              frame-gate      mean   verdict")
    for entry in report["pages"]:
        failures = entry["frame_failures"]
        if failures is None:
            frame = "n/a"
        elif failures:
            frame = f"FAIL ({len(failures)}/12)"
        else:
            frame = "PASS"
        mean = f"{entry['mean']:.1f}" if entry["mean"] is not None else "  -"
        mark = "  <-- best" if entry["position"] == report.get("best_page") else ""
        print(f"  {entry['position']}  {entry['label'][:28]:30} {frame:14} {mean:>6}{mark}")

    if report.get("gap") is not None:
        gap = report["gap"]
        print(f"\n  best mean {report['best_mean']:.1f} "
              f"(ceiling {cs.ARTWORK_PAGE_MAX_MEAN_DISTANCE})"
              f"   rival {report['rival_mean']:.1f}   gap {gap:.1f} "
              f"(needs {cs.ARTWORK_PAGE_MIN_RIVAL_GAP})")
        if report["best_mean"] > cs.ARTWORK_PAGE_MAX_MEAN_DISTANCE:
            print(f"  -> artwork gate would FAIL on ceiling: "
                  f"{report['best_mean']:.1f} > {cs.ARTWORK_PAGE_MAX_MEAN_DISTANCE}")
        if gap < cs.ARTWORK_PAGE_MIN_RIVAL_GAP:
            print(f"  -> artwork gate would FAIL on gap: "
                  f"{gap:.1f} < {cs.ARTWORK_PAGE_MIN_RIVAL_GAP}")

    # The frame gate is what _matching_catalog_positions actually runs.
    first_failures = next(
        (p["frame_failures"] for p in report["pages"] if p["frame_failures"]),
        None,
    )
    if not report["frame_gate_positions"] and first_failures:
        print("\n  frame-gate detail for page 0 (first 4 failing slots):")
        for index, name, hue, target, delta in first_failures[:4]:
            shown = f"{hue:.1f}" if hue is not None else "none"
            gap = f"{delta:.1f}" if delta is not None else "n/a"
            print(f"    slot {index:2} {name[:18]:20} hue {shown:>6} "
                  f"expected {target}  off by {gap}")

    print(f"\n  VERDICT: {report['verdict']}"
          f"   (frame gate matched pages: {report['frame_gate_positions'] or 'none'})")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder = Path(argv[1])
    files = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    if not files:
        print(f"no images in {folder}")
        return 1

    reports = []
    for path in files:
        report = diagnose(path)
        reports.append(report)
        _print(report)

    print(f"\n{'=' * 72}\nSUMMARY\n{'=' * 72}")
    accepted = [r for r in reports if r.get("verdict") == "ACCEPTED"]
    print(f"  images                : {len(reports)}")
    print(f"  accepted              : {len(accepted)}")
    two_rows = [r for r in reports if r.get("rows_accepted") == 2]
    print(f"  gave exactly two rows : {len(two_rows)}")
    print(f"  card-sized components : "
          f"{[r.get('card_sized') for r in reports]}")
    print(f"  six-wide row clusters : "
          f"{[r.get('six_wide_clusters') for r in reports]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
