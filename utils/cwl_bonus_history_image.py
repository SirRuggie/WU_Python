"""PNG of the Lazy bonus winners from the last seasons, one column per season.

Pure function: callers pass stored winners; nothing here reads Discord or the database.
"""
import io
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FILE_NAME = 'Lazy_Bonus_History.png'
_FONTS = Path(__file__).resolve().parents[1] / 'assets' / 'fonts' / 'dejavu'
REGULAR = _FONTS / 'DejaVuSans.ttf'
BOLD = _FONTS / 'DejaVuSans-Bold.ttf'

WIDTH = 1200
MARGIN = 40
TOP = 170
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


def _clean(value):
    # NFKC turns styled letters (for example fullwidth) into plain ones the font can draw.
    return unicodedata.normalize('NFKC', str(value or '')).replace('\n', ' ').strip()


def _fit(draw, value, font, width):
    """Shorten value with an ellipsis until it fits width pixels."""
    if draw.textlength(value, font=font) <= width:
        return value
    while value and draw.textlength(value + '…', font=font) > width:
        value = value[:-1]
    return value + '…'


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
    draw.text((MARGIN, 36), _fit(draw, title, _font(True, 44), WIDTH - 2 * MARGIN), font=_font(True, 44), fill=GOLD)
    text_width = column - 40
    for index, season in enumerate(history):
        x = MARGIN + index * column
        if index:
            draw.line((x - 20, 110, x - 20, height - 30), fill=RULE, width=2)
        winners = sorted(season['winners'], key=lambda row: (_clean(row.get('player_name')).casefold(), row['tag']))
        heading = f"{_clean(season['label'])} · {len(winners)}"
        draw.text((x, 110), _fit(draw, heading, _font(True, 34), text_width), font=_font(True, 34), fill=WHITE)
        if not winners:
            draw.text((x, TOP), 'No winners recorded', font=_font(False, 26), fill=MUTED)
        for row, winner in enumerate(winners):
            y = TOP + row * ROW
            name = _clean(winner.get('player_name')) or _clean(winner['tag'])
            draw.text((x, y), _fit(draw, name, _font(True, 30), text_width), font=_font(True, 30), fill=WHITE)
            draw.text((x, y + 34), _clean(winner['tag']), font=_font(False, 22), fill=MUTED)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()
