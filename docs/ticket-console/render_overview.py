"""
ticket_overview.png — exactly what WU Wizard would draw and attach.
Pillow only. No Cloudinary required. Redrawn whenever a ticket changes state.

This is a raster attachment, not Discord components — so unlike the message
around it (which is bound by real component/character budgets), everything
drawn in here is free-form.

Palette: vibrant, matched to the reference. Colorblind/CVD validation is
explicitly NOT a requirement here, and an earlier CVD-validated palette was
rescinded — read docs/ticket-console.md §3.2 before changing any color.

Flag icons are the actual artwork supplied for Blacklisted / Denied Before /
Not Loyal to WU (assets/tickets/flag_*.png, real alpha transparency, confirmed).
Everything else is hand-drawn with plain PIL shapes (no emoji font) so it
renders identically on any box, no color-emoji-font dependency at deploy.
"""
from PIL import Image, ImageDraw, ImageFont

S = 2  # supersample for crisp text
W, H = 1400, 740
img = Image.new("RGB", (W*S, H*S), "#0b1018")
d = ImageDraw.Draw(img)

def paste_icon(path, cx, cy, size):
    """Paste a real (transparent) icon PNG, cropped to content and centered at (cx,cy)."""
    icon = Image.open(path).convert("RGBA")
    icon = icon.crop(icon.getbbox())
    icon = icon.resize((size*S, size*S), Image.LANCZOS)
    img.paste(icon, (int(cx*S-size*S/2), int(cy*S-size*S/2)), icon)

def F(size, bold=False, mono=False):
    p = "/usr/share/fonts/truetype/dejavu/"
    f = p + ("DejaVuSansMono.ttf" if mono else "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(f, size*S)

def rr(xy, r, fill=None, outline=None, width=1):
    d.rounded_rectangle([c*S for c in xy], radius=r*S, fill=fill, outline=outline, width=width*S)

def txt(x, y, s, font, fill, anchor="la"):
    d.text((x*S, y*S), s, font=font, fill=fill, anchor=anchor)

def line(pts, fill, width):
    d.line([(p[0]*S, p[1]*S) for p in pts], fill=fill, width=width*S, joint="curve")

def tint(hexcol, bg="#1a1c20", amt=0.16):
    """Blend an accent color toward a neutral dark for a tinted card fill.

    `bg` is deliberately #1a1c20 — a touch lighter than the page background
    (#0b1018) — so a tinted card still reads as raised against the canvas.
    Blending toward the true page color flattens the tiles into it.
    """
    h = hexcol.lstrip("#"); b = bg.lstrip("#")
    r1,g1,b1 = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    r2,g2,b2 = int(b[0:2],16), int(b[2:4],16), int(b[4:6],16)
    mix = lambda a,c: round(a*amt + c*(1-amt))
    return "#%02x%02x%02x" % (mix(r1,r2), mix(g1,g2), mix(b1,b2))

INK, MUT, FAINT = "#f2f3f5", "#b5bac1", "#80848e"
CARD = "#111822"
GREEN, BLUE, RED = "#4bce7a", "#4a90f5", "#f0555a"
YELLOW, ORANGE, BL_RED = "#ffcc00", "#f17511", "#dd1c1d"   # sampled straight from the supplied flag icons
LEFT, RIGHT = 36, 1364

# ── icon primitives ──────────────────────────────────────
def icon_check(cx, cy, col):
    line([(cx-8,cy+1),(cx-2,cy+7),(cx+9,cy-8)], col, 3)

def icon_plus(cx, cy, col):
    line([(cx-8,cy),(cx+8,cy)], col, 3); line([(cx,cy-8),(cx,cy+8)], col, 3)

def icon_x(cx, cy, col):
    line([(cx-7,cy-7),(cx+7,cy+7)], col, 3); line([(cx-7,cy+7),(cx+7,cy-7)], col, 3)

def icon_ban(cx, cy, col):
    d.ellipse([(cx-9)*S,(cy-9)*S,(cx+9)*S,(cy+9)*S], outline=col, width=3*S)
    line([(cx-6,cy+6),(cx+6,cy-6)], col, 3)

def icon_shield(cx, topy, w, h, col, fill=None):
    p = [(cx-w/2,topy),(cx+w/2,topy),(cx+w/2,topy+h*0.55),(cx,topy+h),(cx-w/2,topy+h*0.55)]
    d.polygon([(x*S,y*S) for x,y in p], outline=col, width=3*S, fill=fill)

def icon_refresh(cx, cy, r, col):
    bbox = [(cx-r)*S,(cy-r)*S,(cx+r)*S,(cy+r)*S]
    d.arc(bbox, 25, 320, fill=col, width=2*S)
    # arrowhead at the open end (~25°)
    import math
    a = math.radians(25); tx, ty = cx+r*math.cos(a), cy+r*math.sin(a)
    line([(tx-5,ty-2),(tx,ty+4),(tx+5,ty-3)], col, 2)

def icon_bars(x, baseline, col):
    for i,hh in enumerate((11,18,26)):
        xx = x + i*10
        rr((xx, baseline-hh, xx+7, baseline), 2, fill=col)

# ── header ───────────────────────────────────────────────
icon_bars(LEFT, 58, GREEN)
txt(LEFT+40, 26, "Ticket Console — overview", F(27, bold=True), INK)
txt(LEFT+40, 64, "8 tickets · Main 3 · FWA 5", F(16), MUT)
icon_refresh(RIGHT-10, 46, 10, FAINT)
txt(RIGHT-28, 46, "updated just now", F(14), MUT, anchor="rm")

# ── stat tiles — tinted card + matching badge icon ─────────
ty, th = 108, 128
tw = (RIGHT - LEFT - 2*16) // 3
STATUS = [("APPROVED", 2, GREEN, icon_check), ("NEW / OPEN", 2, BLUE, icon_plus), ("DENIED", 4, RED, icon_x)]
for i, (label, n, col, icon) in enumerate(STATUS):
    x = LEFT + i*(tw+16)
    rr((x, ty, x+tw, ty+th), 12, fill=tint(col), outline=col, width=1)
    d.ellipse([(x+tw-46)*S,(ty+18)*S,(x+tw-18)*S,(ty+46)*S], outline=col, width=2*S)
    icon(x+tw-32, ty+32, col)
    txt(x+24, ty+20, str(n), F(46, bold=True), col)
    txt(x+24, ty+88, label, F(15, bold=True), INK)

# ── by clan type — icon + name + plain-English counts + bar ─
by = ty+th+24
head_y, row1top, row_h = by+16, by+56, 96
bh = row_h*2 + 60
rr((LEFT, by, RIGHT, by+bh), 12, fill=CARD)
txt(LEFT+24, head_y, "BY CLAN TYPE", F(14, bold=True), FAINT)
rows = [("Main clan", "assets/tickets/clan_main.png", [(GREEN,1,"approved"),(BLUE,1,"new/open"),(RED,1,"denied")]),
        ("FWA clan",  "assets/tickets/clan_fwa.png",  [(GREEN,1,"approved"),(BLUE,1,"new/open"),(RED,3,"denied")])]
bar_x0, bar_max, maxn = LEFT+96, 1080, 5   # maxn shared across rows so bars stay comparable
for r, (name, clan_icon, segs) in enumerate(rows):
    rowtop = row1top + r*row_h
    paste_icon(clan_icon, LEFT+52, rowtop+24, 68)
    txt(bar_x0, rowtop, name, F(19, bold=True), INK)
    desc = " · ".join(f"{n} {label}" for _,n,label in segs)
    txt(bar_x0, rowtop+27, desc, F(13), MUT)
    total = sum(n for _,n,_ in segs)
    y = rowtop + 54
    x = bar_x0
    for col, n, _ in segs:
        w = int(bar_max * n / maxn) - 2
        rr((x, y, x+w, y+10), 5, fill=col)
        x += w + 2
    txt(x+10, y-3, f"{total} total", F(14, bold=True), INK)

# ── flags — moved under "by clan type", icon badge per row ──
fy = by+bh+20
pill_h, fh = 58, 58+68
rr((LEFT, fy, RIGHT, fy+fh), 12, fill=CARD)
txt(LEFT+24, fy+16, "FLAGS", F(14, bold=True), FAINT)
flags = [("BLACKLISTED", 1, BL_RED, "assets/tickets/flag_blacklisted.png"),
         ("DENIED BEFORE", 1, YELLOW, "assets/tickets/flag_denied_before.png"),
         ("NOT LOYAL TO WU", 1, ORANGE, "assets/tickets/flag_not_loyal.png")]
pw = (RIGHT-24 - (LEFT+24) - 2*16) // 3
py = fy + 46
for i, (label, n, col, icon_path) in enumerate(flags):
    x = LEFT+24 + i*(pw+16)
    rr((x, py, x+pw, py+pill_h), 10, fill=tint(col, amt=0.18), outline=col, width=1)
    paste_icon(icon_path, x+30, py+29, 40)
    txt(x+62, py+18, label, F(14, bold=True), INK)
    txt(x+pw-14, py+18, str(n), F(16, bold=True), col, anchor="ra")

# ── footer ───────────────────────────────────────────────
txt(LEFT, fy+fh+22, "drawn by WU Wizard · attached to the message · redrawn when a ticket changes",
    F(13, mono=True), FAINT)

img = img.resize((W, H), Image.LANCZOS)
img.save("ticket_overview.png", optimize=True)
print("saved", img.size)
