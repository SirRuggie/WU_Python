"""builder-21: every `file:line` citation in docs/lazycwl-dashboard.md must
point at real code, not stale line numbers left behind by an edit. Two
citation shapes are checked (brief builder-21 item 3):

  1. A symbol immediately followed by a parenthesized citation, e.g.
     `` `is_admin(member)` (`lazycwl_dashboard.py:69-74`) `` or
     `` `_encode_auto_on`/`_decode_auto_on` (`:573-590`) `` — for these, the
     cited path/line(s) must actually be where `symbol` lives: the symbol's
     bare name must appear on the cited line, or within the cited N-M range.
  2. Every other `` `path.py:N` ``/`` `:N` `` citation (including the
     `` (`sym`, `path.py:N`) `` combined-parens shape) is bare — only
     checked for every N (an N-M range or comma list of them) being within
     the cited file's length.

A single sequential pass over the document tracks "the file the next bare
`:N` citation belongs to" the same way a human reader would: it updates
whenever a citation names a path explicitly, regardless of shape.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "lazycwl-dashboard.md"

BARE_NAME_TO_PATH = {
    "lazycwl_dashboard.py": "extensions/commands/lazycwl_dashboard.py",
    "lazy_cwl_service.py": "extensions/commands/fwa/lazy_cwl_service.py",
}

ANY_CITATION_RE = re.compile(r"`([^`]*:\d[^`]*)`")
# One or more backtick symbol tokens (no colon), '/'-joined, immediately
# wrapping ONE citation in its own "(`...`)" with nothing else inside -
# e.g. `` `is_admin(member)` (`lazycwl_dashboard.py:69-74`) `` or
# `` `_encode_auto_on`/`_decode_auto_on` (`:573-590`) ``. Deliberately
# stricter than "any backtick token before a citation" so a citation with an
# unrelated backtick word nearby (e.g. reversed path-then-symbol prose) is
# never misread as this shape.
SYMBOL_CITATION_RE = re.compile(
    r"((?:`[^`:]+`/?)+)\s*\(`([^`]*:\d[^`]*)`\)"
)
# A plain module path (no line number) mentioned in prose, e.g.
# `` (`extensions/commands/fwa/lazy_cwl.py`) `` — also moves "the file the
# next bare `:N` belongs to", same as a citation with a number would.
PLAIN_PATH_RE = re.compile(r"`([\w./]+\.py)`")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _resolve_path(raw_path: str) -> Path:
    if "/" in raw_path:
        return REPO_ROOT / raw_path
    return REPO_ROOT / BARE_NAME_TO_PATH[raw_path]


def _split_citation(citation: str):
    """"path:N,M-K" -> (path_or_empty, [N, (M, K), ...])."""
    path_part, _, nums_part = citation.partition(":")
    chunks = []
    for piece in nums_part.split(","):
        piece = piece.strip()
        if "-" in piece:
            start, end = piece.split("-", 1)
            chunks.append((int(start), int(end)))
        else:
            chunks.append(int(piece))
    return path_part, chunks


def _symbol_bare_name(symbol_text: str) -> str:
    """`is_admin(member)` -> `is_admin`; `REMOVE_MAX_PICK = 8` ->
    `REMOVE_MAX_PICK`; `LazyCwl.invoke` -> `invoke` (the citation targets
    the method's own definition line, not the class line)."""
    name = symbol_text.split("(")[0].split("=")[0].strip()
    return name.rsplit(".", 1)[-1]


def _parse_citations():
    """One ordered pass -> (symbol_items, bare_items).
    symbol_items: [(symbols: list[str], citation: str)]
    bare_items: [(citation: str,)]
    `current_file` (the file a path-less `:N` belongs to) updates on every
    citation that names a path, symbol-attached or not."""
    text = DOC_PATH.read_text()
    current_file = "lazycwl_dashboard.py"  # doc opens describing this file
    symbol_items = []
    bare_items = []

    # citation-group span -> [symbols], for every strict "symbol (`citation`)" match.
    symbols_by_span = {}
    for sym_match in SYMBOL_CITATION_RE.finditer(text):
        symbols_blob = sym_match.group(1)
        symbols = [s.strip("`") for s in symbols_blob.strip("/").split("/") if s.strip("`")]
        symbols_by_span[sym_match.span(2)] = symbols

    # Merge citation matches and plain-path mentions into one ordered pass
    # so "the current file" tracks both kinds of path mention in reading order.
    events = [("citation", m) for m in ANY_CITATION_RE.finditer(text)]
    events += [("path", m) for m in PLAIN_PATH_RE.finditer(text)]
    events.sort(key=lambda pair: pair[1].start())

    for kind, match in events:
        if kind == "path":
            current_file = match.group(1)
            continue

        citation = match.group(1)
        path_part, _chunks = _split_citation(citation)
        effective_path = path_part or current_file
        if path_part:
            current_file = path_part

        symbols = symbols_by_span.get(match.span(1))
        if symbols:
            symbol_items.append((symbols, effective_path, citation))
        else:
            bare_items.append((effective_path, citation))

    return symbol_items, bare_items


def test_symbol_citations_point_at_the_symbols_definition():
    """MUST-FIX (refuter-19): every `` `symbol` (`:N`) `` style citation must
    still land on a line that actually mentions that symbol's bare name."""
    symbol_items, _bare_items = _parse_citations()
    failures = []

    for symbols, effective_path, citation in symbol_items:
        try:
            file_path = _resolve_path(effective_path)
        except KeyError as exc:
            failures.append(f"{symbols} -> {citation!r}: cannot resolve path ({exc})")
            continue
        if not file_path.exists():
            failures.append(f"{symbols} -> {citation!r}: {file_path} does not exist")
            continue
        lines = file_path.read_text().splitlines()
        _path_part, chunks = _split_citation(citation)
        for chunk in chunks:
            start_n, end_n = chunk if isinstance(chunk, tuple) else (chunk, chunk)
            window = "\n".join(lines[max(0, start_n - 1):end_n])
            for symbol in symbols:
                bare = _symbol_bare_name(symbol)
                # Markdown-escaped backticks inside a quoted string literal
                # (e.g. MOVED_NOTICE's own text) can truncate the symbol
                # token mid-string; only check tokens that parse as a real
                # Python identifier.
                if not IDENTIFIER_RE.match(bare):
                    continue
                if bare not in window:
                    failures.append(
                        f"`{symbol}` (`{citation}`): {bare!r} not found on "
                        f"{file_path.relative_to(REPO_ROOT)}:{start_n}"
                        + (f"-{end_n}" if end_n != start_n else "")
                    )

    if failures:
        raise AssertionError(
            f"{len(failures)} stale/wrong doc citation(s):\n" + "\n".join(failures)
        )


def test_bare_path_citations_are_within_file_length():
    """Every other citation (including the `` (`sym`, `path:N`) `` combined
    shape) only needs N (and every number of an N-M range or comma list) to
    be within the cited file's line count (brief builder-21 item 3's weaker
    bare-citation check)."""
    _symbol_items, bare_items = _parse_citations()
    failures = []

    for effective_path, citation in bare_items:
        try:
            file_path = _resolve_path(effective_path)
        except KeyError as exc:
            failures.append(f"{citation!r}: cannot resolve path ({exc})")
            continue
        if not file_path.exists():
            failures.append(f"{citation!r}: {file_path} does not exist")
            continue
        line_count = len(file_path.read_text().splitlines())
        _path_part, chunks = _split_citation(citation)
        for chunk in chunks:
            nums = chunk if isinstance(chunk, tuple) else (chunk,)
            for n in nums:
                if n > line_count:
                    failures.append(
                        f"{citation!r}: line {n} > {file_path.relative_to(REPO_ROOT)}'s "
                        f"{line_count} lines"
                    )

    if failures:
        raise AssertionError(
            f"{len(failures)} out-of-range doc citation(s):\n" + "\n".join(failures)
        )
