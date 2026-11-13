"""PNG of the Lazy bonus winners from the last seasons, one column per season.

Pure function: callers pass stored winners; nothing here reads Discord or the database.
Player names can hold any Unicode text, so names draw with a font fallback chain.
"""
import io
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FILE_NAME = 'Lazy_Bonus_History.png'
_ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'fonts'
REGULAR = _ASSETS / 'dejavu' / 'DejaVuSans.ttf'
BOLD = _ASSETS / 'dejavu' / 'DejaVuSans-Bold.ttf'
# Tried in order for each character DejaVu cannot draw. Unifont is last: it covers the
# rest of the Basic Multilingual Plane (for example CJK and Hangul). The Egyptian font
# draws the decorative brackets U+131A9 and U+131AA used in names.
FALLBACKS = (
    'noto/NotoSansSymbols2-Regular.ttf',
    'noto/NotoSansSymbols-VF.ttf',
    'noto/NotoSansMath-Regular.ttf',
    'noto/NotoEmoji-VF.ttf',
    'noto/NotoSansJavanese-VF.ttf',
    'noto/NotoSansArabic-VF.ttf',
    'noto/NotoSansThai-VF.ttf',
    'noto/NotoSansEgyptianHieroglyphs-Regular.ttf',
    'unifont/unifont.otf',
)
# A noncharacter: no font has it, so it draws the font's "missing glyph" box.
_MISSING = '￿'

WIDTH = 1200
MARGIN = 40
TOP = 205
ROW = 64
BOTTOM = 40
BACKGROUND = '#17181B'
GOLD = '#F2B62A'
WHITE = '#F5F4F0'
MUTED = '#A9ADB5'
RULE = '#33363C'


@lru_cache(maxsize=None)
def _font(bold, size):
    return ImageFont.truetype(str(BOLD if bold else REGULAR), size)


@lru_cache(maxsize=None)
def _chain(bold, size):
    fonts = [_font(bold, size)]
    for name in FALLBACKS:
        font = ImageFont.truetype(str(_ASSETS / name), size)
        if bold:
            try:
                font.set_variation_by_name('Bold')
            except (OSError, ValueError):
                pass  # Static font without a Bold instance: use its regular weight.
        fonts.append(font)
    return tuple(fonts)


def _signature(font, char):
    mask = font.getmask(char)
    return mask.size, bytes(mask)


@lru_cache(maxsize=None)
def _missing(font):
    return _signature(font, _MISSING)


@lru_cache(maxsize=4096)
def _has(font, char):
    return _signature(font, char) != _missing(font)


def _joins(char):
    # Marks, joiners and variation selectors stay with the character before them.
    return unicodedata.category(char) in ('Mn', 'Me', 'Cf') or char.isspace()


def runs(text, fonts):
    """Split text into (part, font) runs; each character uses the first font that has it."""
    result = []
    for char in text:
        if _joins(char) and result:
            result[-1][0] += char
            continue
        font = next((f for f in fonts if _has(f, char)), fonts[-1])
        if result and result[-1][1] is font:
            result[-1][0] += char
        else:
            result.append([char, font])
    return [(part, font) for part, font in result]


def _width(draw, parts):
    return sum(draw.textlength(part, font=font) for part, font in parts)


def _fit(draw, value, fonts, width):
    """Return runs for value, shortened with an ellipsis until they fit width pixels."""
    parts = runs(value, fonts)
    if _width(draw, parts) <= width:
        return parts
    while value:
        value = value[:-1]
        parts = runs(value + '…', fonts)
        if _width(draw, parts) <= width:
            return parts
    return runs('…', fonts)


def _draw(draw, x, baseline, value, fonts, width, fill):
    for part, font in _fit(draw, value, fonts, width):
        draw.text((x, baseline), part, font=font, fill=fill, anchor='ls')
        x += draw.textlength(part, font=font)


def _clean(value):
    # NFKC turns styled letters (for example fullwidth) into plain ones the font can draw.
    return unicodedata.normalize('NFKC', str(value or '')).replace('\n', ' ').strip()


def alt_text(history):
    """Short image description for screen readers: seasons and counts, never the full list."""
    parts = [f"{season['label']}: {len(season['winners'])}" for season in history]
    return 'Lazy CWL bonus winners by season. ' + ', '.join(parts) + '.'


def render(history, title='Lazy CWL bonus winners · last 3 seasons'):
    """Return PNG bytes. history: oldest season first, each {'label', 'winners': [{'tag', 'player_name'}]}."""
    columns = max(1, len(history))
    column = (WIDTH - 2 * MARGIN) // columns
    rows = max([len(season['winners']) for season in history] + [1])
    height = TOP + rows * ROW + BOTTOM
    image = Image.new('RGB', (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 10), fill=GOLD)
    # Baselines match the earlier top-anchored layout: the top plus the font's ascent.
    _draw(draw, MARGIN, 36 + _font(True, 44).getmetrics()[0], title, (_font(True, 44),), WIDTH - 2 * MARGIN, GOLD)
    text_width = column - 40
    names = _chain(True, 30)
    for index, season in enumerate(history):
        x = MARGIN + index * column
        if index:
            draw.line((x - 20, 110, x - 20, height - 30), fill=RULE, width=2)
        winners = sorted(season['winners'], key=lambda row: (_clean(row.get('player_name')).casefold(), row['tag']))
        # Month and year, then the count in small text (Ruggie, 2026-11-13).
        _draw(draw, x, 110 + _font(True, 34).getmetrics()[0], _clean(season['label']), (_font(True, 34),), text_width, WHITE)
        count = len(winners)
        note = 'No bonus winners' if not count else f"{count} bonus winner{'s' if count != 1 else ''}"
        _draw(draw, x, 152 + _font(False, 24).getmetrics()[0], note, (_font(False, 24),), text_width, MUTED)
        for row, winner in enumerate(winners):
            y = TOP + row * ROW
            name = _clean(winner.get('player_name')) or _clean(winner['tag'])
            _draw(draw, x, y + names[0].getmetrics()[0], name, names, text_width, WHITE)
            _draw(draw, x, y + 34 + _font(False, 22).getmetrics()[0], _clean(winner['tag']), (_font(False, 22),), text_width, MUTED)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()
