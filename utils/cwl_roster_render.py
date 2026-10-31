"""Deterministic published roster PNGs, independent of HTTP and bot transport."""
import io
import math
import unicodedata
from pathlib import Path
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageOps
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

@lru_cache(maxsize=1)
def background_art():
    with Image.open(Path(__file__).resolve().parents[1] / 'cwl_web' / 'assets' / 'roster-background.jpg') as image:
        return ImageOps.exif_transpose(image).convert('RGB')

def render(season, pub, group, page):
    pages = math.ceil(len(group['accounts']) / 15)
    if page < 1 or page > pages:
        raise ValueError('Unknown image page.')
    players = group['accounts'][(page - 1) * 15:page * 15]
    width = 1000
    height = 300 + len(players) * 70 + 90
    im = Image.new('RGB', (width, height), '#111214')
    art = ImageOps.pad(background_art(), (width, height), method=Image.Resampling.LANCZOS, color='#111214')
    im = Image.blend(im, art, 0.28)
    d = ImageDraw.Draw(im, 'RGBA')
    gold = '#f4cd64'
    white = '#f5f4f0'
    muted = '#bfc2c8'

    def text(x, y, value, size, color=white, maxwidth=900, bold=False):
        value = unicodedata.normalize('NFKC', str(value)).replace('\n', ' ')
        font = ImageFont.truetype(BOLD if bold else FONT, size)
        while d.textlength(value, font=font) > maxwidth and size > 12:
            size -= 1
            font = ImageFont.truetype(BOLD if bold else FONT, size)
        while d.textlength(value, font=font) > maxwidth and len(value) > 1:
            value = value[:-2] + '…'
        d.text((x, y), value, font=font, fill=color)
    d.rectangle((0, 0, width, 10), fill=gold)
    text(42, 32, 'WARRIORS UNITED', 38, gold, bold=True)
    text(42, 90, f"{season['label']} · {('Main' if group['pool'] == 'main' else 'Lazy')} CWL", 25, muted)
    text(42, 140, group['name'], 38, bold=True)
    text(42, 196, f"{group['tag']} · {group['league']}", 24, muted)
    text(42, 240, f"FINAL ROSTER · VERSION {pub['version']}", 18, gold)
    for i, a in enumerate(players):
        y = 290 + i * 70
        d.rounded_rectangle((32, y, 968, y + 60), radius=10, fill=(28, 29, 33, 150) if i % 2 == 0 else (17, 18, 21, 150), outline='#4a4431')
        text(48, y + 16, str((page - 1) * 15 + i + 1), 20, gold, maxwidth=45, bold=True)
        text(104, y + 14, a['player_name'], 25, maxwidth=440, bold=True)
        text(560, y + 18, a['tag'], 20, muted, maxwidth=250)
        text(855, y + 16, f"TH {a['town_hall']}", 21, gold, maxwidth=100, bold=True)
    text(42, height - 66, f"{len(group['accounts'])} players · Page {page}/{pages}", 22, gold)
    d.rectangle((0, height - 10, width, height), fill=gold)
    buf = io.BytesIO()
    im.save(buf, format='PNG')
    return buf.getvalue()
