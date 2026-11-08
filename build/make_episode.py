#!/usr/bin/env python3
"""Render Episode 1 as 2D motion graphics with Hindi voices, music and sound effects."""
import asyncio, hashlib, math, os, random, subprocess, textwrap, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import edge_tts
import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "output")
CACHE = os.path.join(HERE, "cache")
os.makedirs(OUT, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS, SR = 720, 1280, 24, 44100
FONT_PATH = "/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf"
FONT = {s: ImageFont.truetype(FONT_PATH, s) for s in (26, 30, 34, 44, 60)}

VOICES = {
    "narr":   dict(voice="hi-IN-MadhurNeural", rate="-5%",  pitch="-4Hz",  name="Narrator", color=(255, 236, 170)),
    "raja":   dict(voice="hi-IN-MadhurNeural", rate="-8%",  pitch="-18Hz", name="Raja Sher Singh", color=(255, 215, 0)),
    "rocky":  dict(voice="hi-IN-MadhurNeural", rate="+12%", pitch="+14Hz", name="Rocky", color=(255, 140, 60)),
    "rani":   dict(voice="hi-IN-SwaraNeural",  rate="+0%",  pitch="+0Hz",  name="Rani", color=(120, 230, 210)),
    "anno":   dict(voice="hi-IN-MadhurNeural", rate="+18%", pitch="+6Hz",  name="Announcer", color=(230, 120, 255)),
    "chintu": dict(voice="hi-IN-SwaraNeural",  rate="+25%", pitch="+45Hz", name="Chintu", color=(200, 160, 120)),
}


# ---------- drawing helpers (integer-cast wrappers around ImageDraw) ----------
def I(v):
    return int(round(v))


def ell(d, x0, y0, x1, y1, **k):
    d.ellipse([I(x0), I(y0), I(x1), I(y1)], **k)


def circ(d, cx, cy, r, **k):
    ell(d, cx - r, cy - r, cx + r, cy + r, **k)


def rrect(d, x0, y0, x1, y1, r, **k):
    d.rounded_rectangle([I(x0), I(y0), I(x1), I(y1)], radius=max(1, I(r)), **k)


def rect(d, x0, y0, x1, y1, **k):
    d.rectangle([I(x0), I(y0), I(x1), I(y1)], **k)


def ln(d, pts, w=3, **k):
    d.line([(I(x), I(y)) for x, y in pts], width=max(1, I(w)), **k)


def arc(d, x0, y0, x1, y1, a0, a1, w=3, **k):
    d.arc([I(x0), I(y0), I(x1), I(y1)], a0, a1, width=max(1, I(w)), **k)


def poly(d, pts, **k):
    d.polygon([(I(x), I(y)) for x, y in pts], **k)


# ---------- backgrounds ----------
THEMES = {
    "mansion": ((30, 28, 70), (150, 80, 60)),
    "hall": ((70, 36, 14), (22, 12, 6)),
    "stadium": ((14, 12, 44), (80, 30, 90)),
    "night": ((3, 4, 14), (22, 24, 62)),
}


def make_bg(theme):
    top, bot = THEMES[theme]
    t = np.linspace(0, 1, H)[:, None]
    arr = np.zeros((H, W, 3), np.uint8)
    for c in range(3):
        arr[:, :, c] = (top[c] * (1 - t) + bot[c] * t).astype(np.uint8)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    rng = random.Random(3)
    if theme == "mansion":
        for i in range(12):
            x = i * 62 - 10
            h = rng.randint(260, 520)
            rect(d, x, 900 - h, x + 56, 900, fill=(40, 34, 70))
            for wy in range(900 - h + 20, 880, 46):
                if rng.random() < 0.5:
                    rect(d, x + 14, wy, x + 26, wy + 16, fill=(255, 210, 110))
        rrect(d, 120, 560, 600, 900, 10, fill=(90, 60, 50), outline=(40, 25, 20), width=3)
        for wx in (170, 300, 430, 550):
            rect(d, wx, 620, wx + 40, 680, fill=(255, 220, 130))
        rect(d, 0, 900, W, H, fill=(40, 60, 40))
    elif theme == "hall":
        for x in (60, 230, 490, 660):
            rect(d, x - 18, 150, x + 18, 900, fill=(110, 70, 30))
        rect(d, 0, 900, W, H, fill=(90, 56, 22))
    elif theme == "stadium":
        for i in range(-2, 4):
            poly(d, [(360, 0), (360 + i * 120 - 40, 900), (360 + i * 120 + 40, 900)], fill=(36, 34, 70))
        for row in range(5):
            rect(d, 0, 300 + row * 40, W, 320 + row * 40, fill=(60 + row * 8, 30, 80))
        rect(d, 0, 900, W, H, fill=(40, 90, 60))
    elif theme == "night":
        for _ in range(120):
            circ(d, rng.randint(0, W), rng.randint(0, 650), rng.choice([1, 2]), fill=(255, 255, 230))
        circ(d, 600, 170, 60, fill=(250, 245, 220))
        rect(d, 0, 900, W, H, fill=(12, 18, 30))
    return img


# ---------- characters ----------
LION = {
    "raja":  dict(body=(250, 250, 248), mane=(240, 236, 222), face=(246, 228, 190)),
    "rocky": dict(body=(226, 170, 36), mane=(200, 122, 42), face=(232, 168, 92)),
    "rani":  dict(body=(40, 150, 140), mane=None, face=(236, 184, 112)),
}
# (inner brow offset, outer brow offset) in units of head radius; negative is up
BROW = {"neutral": (0, 0), "angry": (0.16, -0.06), "sad": (-0.16, 0.04), "shock": (-0.22, -0.22),
        "happy": (-0.06, -0.08), "proud": (-0.06, -0.06), "calm": (0.02, 0.02), "smug": (-0.08, -0.2)}


def draw_mouth(d, cx, my, w, mouth, expr):
    lw = max(2, int(w * 0.25))
    if mouth > 0.08:
        oh = w * (0.5 + 2.0 * mouth)
        ell(d, cx - w, my, cx + w, my + oh, fill=(110, 25, 35), outline=(40, 10, 10), width=2)
    elif expr in ("happy", "proud", "smug", "calm"):
        arc(d, cx - w, my - 0.8 * w, cx + w, my + 0.8 * w, 20, 160, w=lw, fill=(60, 20, 20))
    elif expr in ("sad", "angry", "shock"):
        arc(d, cx - w, my, cx + w, my + 1.6 * w, 200, 340, w=lw, fill=(60, 20, 20))
    else:
        ln(d, [(cx - w, my), (cx + w, my)], w=lw, fill=(60, 20, 20))


def draw_face(d, cx, cy, r, expr, blink, shades, look):
    ex, ey = 0.36 * r, cy - 0.1 * r
    if shades:
        rrect(d, cx - 0.66 * r, ey - 0.2 * r, cx + 0.66 * r, ey + 0.2 * r, 0.12 * r,
              fill=(15, 15, 15), outline=(0, 0, 0), width=2)
    else:
        for sx in (-1, 1):
            ox = cx + sx * ex
            if blink:
                ln(d, [(ox - 0.2 * r, ey), (ox + 0.2 * r, ey)], w=max(2, 0.05 * r), fill=(30, 20, 10))
            else:
                ell(d, ox - 0.2 * r, ey - 0.15 * r, ox + 0.2 * r, ey + 0.15 * r,
                    fill=(255, 255, 255), outline=(30, 20, 10), width=2)
                circ(d, ox + look * 0.06 * r, ey, 0.08 * r, fill=(20, 15, 10))
    base = cy - 0.42 * r
    for sx in (-1, 1):
        inner, outer = BROW.get(expr, (0, 0))
        if expr == "smug" and sx == -1:
            inner, outer = 0, 0
        ox = cx + sx * ex
        ln(d, [(ox + sx * 0.2 * r, base + outer * r), (ox - sx * 0.2 * r, base + inner * r)],
           w=max(3, 0.05 * r), fill=(40, 25, 15))


def draw_lion(d, a, t, mouth):
    x, y, s = a["x"], a["y"], a["s"]
    r = 105 * s
    cy = y + math.sin(t * 2.4 + a["ph"]) * 3 * s
    cfg = LION[a["id"]]
    rrect(d, x - 0.95 * r, cy + 0.85 * r, x + 0.95 * r, cy + 2.75 * r, 0.5 * r,
          fill=cfg["body"], outline=(30, 30, 30), width=3)
    if cfg["mane"]:
        circ(d, x, cy, 1.2 * r, fill=cfg["mane"])
        for k in range(14):
            ang = 2 * math.pi * k / 14
            circ(d, x + math.cos(ang) * 1.15 * r, cy + math.sin(ang) * 1.15 * r, 0.32 * r,
                 fill=cfg["mane"], outline=(120, 90, 50), width=2)
    else:
        for sx in (-1, 1):
            circ(d, x + sx * 0.72 * r, cy - 0.72 * r, 0.3 * r, fill=cfg["face"], outline=(30, 30, 30), width=2)
    circ(d, x, cy, r, fill=cfg["face"], outline=(40, 30, 20), width=3)
    blink = ((t + a["ph"]) % 3.4) < 0.12
    draw_face(d, x, cy, r, a["expr"], blink, a.get("shades", False), a.get("look", 0))
    ell(d, x - 0.09 * r, cy + 0.1 * r, x + 0.09 * r, cy + 0.22 * r, fill=(110, 60, 45))
    draw_mouth(d, x, cy + 0.55 * r, 0.28 * r, mouth, a["expr"])
    # accessories drawn last so they sit over the chest
    if a["id"] == "raja":
        ln(d, [(x - 0.35 * r, cy + 0.9 * r), (x, cy + 1.6 * r), (x + 0.35 * r, cy + 0.9 * r)], w=3, fill=(120, 120, 120))
        arc(d, x - 0.55 * r, cy + 0.9 * r, x + 0.55 * r, cy + 1.7 * r, 10, 170, w=6, fill=(255, 200, 0))
        circ(d, x, cy + 1.72 * r, 0.08 * r, fill=(255, 200, 0))
        circ(d, x + 0.9 * r, cy + 1.5 * r, 0.14 * r, fill=(255, 200, 0), outline=(120, 80, 0), width=2)
    elif a["id"] == "rocky":
        ln(d, [(x, cy + 0.9 * r), (x, cy + 2.7 * r)], w=3, fill=(120, 80, 0))
    elif a["id"] == "rani":
        poly(d, [(x - 0.4 * r, cy + 0.9 * r), (x, cy + 1.5 * r), (x + 0.4 * r, cy + 0.9 * r)], fill=(230, 230, 220))


def draw_tiger(d, a, t, mouth):
    x, y, s = a["x"], a["y"], a["s"]
    r = 100 * s
    cy = y + math.sin(t * 2.0 + a["ph"]) * 3 * s
    ell(d, x - 1.2 * r, cy + 0.85 * r, x + 1.2 * r, cy + 2.7 * r, fill=(245, 245, 240), outline=(40, 40, 40), width=3)
    for k in (-2, -1, 0, 1, 2):
        ln(d, [(x + k * 0.4 * r, cy + 1.2 * r), (x + k * 0.4 * r + 0.1 * r, cy + 1.9 * r)], w=6, fill=(30, 30, 30))
    rrect(d, x - 0.85 * r, cy + 0.85 * r, x + 0.85 * r, cy + 1.05 * r, 0.08 * r,
          fill=(255, 200, 40), outline=(150, 100, 0), width=2)
    for sx in (-1, 1):
        circ(d, x + sx * 0.7 * r, cy - 0.7 * r, 0.3 * r, fill=(245, 245, 240), outline=(40, 40, 40), width=3)
    circ(d, x, cy, r, fill=(248, 248, 244), outline=(40, 40, 40), width=3)
    for sx in (-1, 0, 1):
        ln(d, [(x + sx * 0.25 * r, cy - 0.95 * r), (x + sx * 0.25 * r, cy - 0.55 * r)], w=max(3, 0.08 * r), fill=(30, 30, 30))
    blink = ((t + a["ph"]) % 3.0) < 0.1
    for sx in (-1, 1):
        ox, ey = x + sx * 0.38 * r, cy - 0.1 * r
        if blink:
            ln(d, [(ox - 0.2 * r, ey), (ox + 0.2 * r, ey)], w=3, fill=(30, 20, 10))
        else:
            circ(d, ox, ey, 0.2 * r, fill=(50, 140, 255), outline=(20, 20, 20), width=2)
            circ(d, ox, ey, 0.09 * r, fill=(10, 10, 10))
    ell(d, x - 0.15 * r, cy + 0.2 * r, x + 0.15 * r, cy + 0.32 * r, fill=(230, 120, 130))
    draw_mouth(d, x, cy + 0.55 * r, 0.3 * r, mouth, a["expr"])


def draw_rat(d, a, t, mouth):
    x, y, s = a["x"], a["y"], a["s"]
    r = 60 * s
    cy = y + math.sin(t * 3.0 + a["ph"]) * 2 * s
    ln(d, [(x + 1.0 * r, cy + 1.5 * r), (x + 2.0 * r, cy + 1.3 * r), (x + 2.4 * r, cy + 0.6 * r)],
       w=max(2, 0.12 * r), fill=(190, 130, 110))
    ell(d, x - 1.1 * r, cy + 0.7 * r, x + 1.1 * r, cy + 2.0 * r, fill=(139, 90, 43), outline=(60, 35, 15), width=2)
    rnd = random.Random(7)  # fixed seed keeps the scruffy tufts still between frames
    for _ in range(12):
        bx = x + rnd.uniform(-0.9, 0.9) * r
        by = cy + rnd.uniform(1.0, 1.9) * r
        ln(d, [(bx, by), (bx + 0.15 * r, by - 0.25 * r)], w=2, fill=(90, 55, 25))
    for sx in (-1, 1):
        circ(d, x + sx * 0.62 * r, cy - 0.72 * r, 0.36 * r, fill=(236, 160, 160), outline=(60, 35, 15), width=2)
    circ(d, x, cy, 0.85 * r, fill=(150, 100, 50), outline=(60, 35, 15), width=2)
    blink = ((t + a["ph"]) % 3.0) < 0.1
    for sx in (-1, 1):
        if blink:
            ln(d, [(x + sx * 0.25 * r, cy - 0.1 * r), (x + sx * 0.41 * r, cy - 0.1 * r)], w=2, fill=(10, 10, 10))
        else:
            circ(d, x + sx * 0.33 * r, cy - 0.1 * r, 0.12 * r, fill=(10, 10, 10))
    circ(d, x, cy + 0.3 * r, 0.14 * r, fill=(40, 20, 20))
    for sx in (-1, 1):
        ln(d, [(x + sx * 0.35 * r, cy + 0.35 * r), (x + sx * 1.0 * r, cy + 0.2 * r)], w=2, fill=(230, 230, 230))
        ln(d, [(x + sx * 0.35 * r, cy + 0.45 * r), (x + sx * 1.0 * r, cy + 0.5 * r)], w=2, fill=(230, 230, 230))
    draw_mouth(d, x, cy + 0.5 * r, 0.18 * r, mouth, a["expr"])


def draw_crowd(d, y, cheer, t):
    cols = [(230, 80, 80), (80, 160, 230), (250, 200, 60), (120, 220, 120), (200, 120, 230), (240, 140, 60)]
    for row in range(2):
        for i in range(13):
            cx = 30 + i * 56 + row * 28
            cy = y - row * 48
            bob = math.sin(t * (3 + i % 3) + i) * (9 if cheer else 2)
            c = cols[(i + row) % len(cols)]
            if cheer:
                ln(d, [(cx - 18, cy + bob + 10), (cx - 30, cy + bob - 30)], w=5, fill=c)
                ln(d, [(cx + 18, cy + bob + 10), (cx + 30, cy + bob - 30)], w=5, fill=c)
            rrect(d, cx - 22, cy + bob + 18, cx + 22, cy + bob + 60, 12, fill=c)
            circ(d, cx, cy + bob, 20, fill=c, outline=(20, 20, 20), width=2)


# ---------- props ----------
def prop_car(d, x, y, s, **_):
    rrect(d, x - 150 * s, y - 50 * s, x + 150 * s, y + 20 * s, 30 * s, fill=(250, 200, 20), outline=(60, 40, 0), width=3)
    poly(d, [(x - 70 * s, y - 50 * s), (x - 40 * s, y - 95 * s), (x + 60 * s, y - 95 * s), (x + 95 * s, y - 50 * s)],
         fill=(250, 200, 20), outline=(60, 40, 0))
    poly(d, [(x - 60 * s, y - 55 * s), (x - 35 * s, y - 88 * s), (x + 55 * s, y - 88 * s), (x + 85 * s, y - 55 * s)],
         fill=(40, 60, 110))
    for wx in (-90, 90):
        circ(d, x + wx * s, y + 20 * s, 35 * s, fill=(25, 25, 25))
        circ(d, x + wx * s, y + 20 * s, 15 * s, fill=(170, 170, 170))


def prop_throne(d, x, y, s, **_):
    rrect(d, x - 120 * s, y - 290 * s, x + 120 * s, y - 30 * s, 20 * s, fill=(212, 160, 40), outline=(120, 80, 0), width=4)
    rrect(d, x - 150 * s, y - 40 * s, x + 150 * s, y + 30 * s, 15 * s, fill=(160, 20, 40), outline=(90, 10, 20), width=3)


def prop_box(d, x, y, s, **_):
    rect(d, x - 110 * s, y - 60 * s, x + 110 * s, y + 70 * s, fill=(176, 128, 70), outline=(90, 60, 30), width=3)
    rect(d, x - 120 * s, y - 80 * s, x + 120 * s, y - 55 * s, fill=(200, 150, 90), outline=(90, 60, 30), width=3)


def prop_podium(d, x, y, s, **_):
    rrect(d, x - 110 * s, y - 120 * s, x + 110 * s, y + 200 * s, 10 * s, fill=(60, 60, 85), outline=(20, 20, 30), width=3)
    ln(d, [(x, y - 120 * s), (x, y - 200 * s)], w=4, fill=(30, 30, 30))
    circ(d, x, y - 210 * s, 14 * s, fill=(40, 40, 40))


def prop_trophy(d, x, y, s, **_):
    arc(d, x - 85 * s, y - 70 * s, x - 40 * s, y - 20 * s, 90, 270, w=6 * s, fill=(230, 180, 30))
    arc(d, x + 40 * s, y - 70 * s, x + 85 * s, y - 20 * s, 270, 90, w=6 * s, fill=(230, 180, 30))
    poly(d, [(x - 60 * s, y - 80 * s), (x + 60 * s, y - 80 * s), (x + 40 * s, y), (x - 40 * s, y)],
         fill=(255, 205, 50), outline=(120, 80, 0))
    rect(d, x - 12 * s, y, x + 12 * s, y + 40 * s, fill=(230, 180, 40))
    rect(d, x - 50 * s, y + 40 * s, x + 50 * s, y + 60 * s, fill=(120, 70, 20))


def prop_key(d, x, y, s, **_):
    circ(d, x, y, 22 * s, fill=(255, 200, 40), outline=(140, 90, 0), width=3)
    circ(d, x, y, 8 * s, fill=(40, 30, 10))
    rect(d, x + 18 * s, y - 7 * s, x + 90 * s, y + 7 * s, fill=(255, 200, 40), outline=(140, 90, 0), width=2)
    rect(d, x + 70 * s, y + 7 * s, x + 80 * s, y + 24 * s, fill=(255, 200, 40))
    rect(d, x + 84 * s, y + 7 * s, x + 94 * s, y + 20 * s, fill=(255, 200, 40))


def prop_block(d, x, y, s, w=200, h=100, **_):
    x0, x1 = x - w * s / 2, x + w * s / 2
    y0, y1 = y - h * s / 2, y + h * s / 2
    rect(d, x0, y0, x1, y1, fill=(150, 95, 50), outline=(80, 45, 20), width=4)
    for k in (1, 2, 3):
        ln(d, [(x0, y0 + k * (y1 - y0) / 4), (x1, y0 + k * (y1 - y0) / 4)], w=2, fill=(90, 55, 25))


def prop_maze(d, x, y, s, **_):
    size = 300 * s
    x0, y0 = x - size / 2, y - size / 2
    step = size / 6
    rect(d, x0, y0, x0 + size, y0 + size, outline=(120, 220, 255), width=3)
    walls = [(0, 1, 3, 1), (2, 0, 2, 3), (1, 3, 4, 3), (3, 2, 3, 5), (4, 1, 5, 1), (4, 4, 5, 4), (1, 5, 2, 5)]
    for c1, r1, c2, r2 in walls:
        ln(d, [(x0 + c1 * step, y0 + r1 * step), (x0 + c2 * step, y0 + r2 * step)], w=8 * s, fill=(120, 220, 255))
    circ(d, x0 + step * 0.5, y0 + step * 0.5, 10 * s, fill=(255, 80, 80))
    circ(d, x0 + size - step * 0.5, y0 + size - step * 0.5, 10 * s, fill=(80, 255, 120))


def prop_tunnel(d, x, y, s, w=420, **_):
    rrect(d, x - w * s / 2, y - 70 * s, x + w * s / 2, y + 70 * s, 60 * s,
          fill=(40, 30, 30), outline=(120, 90, 60), width=6)
    rrect(d, x - w * s / 2 + 30 * s, y - 30 * s, x + w * s / 2 - 30 * s, y + 30 * s, 25 * s, fill=(15, 10, 10))


PROPS = {"car": prop_car, "throne": prop_throne, "box": prop_box, "podium": prop_podium,
         "trophy": prop_trophy, "key": prop_key, "block": prop_block, "maze": prop_maze, "tunnel": prop_tunnel}
ACTOR_FN = {"raja": draw_lion, "rocky": draw_lion, "rani": draw_lion, "chintu": draw_rat, "tiger": draw_tiger}


# ---------- text overlays ----------
def draw_banner(d, text):
    rrect(d, 40, 40, W - 40, 170, 22, fill=(170, 20, 40), outline=(255, 200, 0), width=5)
    for i, line in enumerate(textwrap.wrap(text, 24)):
        d.text((W // 2, 105 + i * 40), line, font=FONT[34], fill=(255, 255, 255), anchor="mm")


def draw_title(d, blocks):
    y = 440
    for i, (txt, size) in enumerate(blocks):
        color = (255, 215, 0) if i == 0 else (255, 255, 255)
        for line in textwrap.wrap(txt, 20 if size >= 44 else 36):
            d.text((W // 2, y), line, font=FONT[size], fill=color, anchor="mm")
            y += size + 14
        y += 30


def draw_subtitle(d, spk, text):
    name, col = VOICES[spk]["name"], VOICES[spk]["color"]
    rrect(d, 24, 1030, W - 24, 1245, 22, fill=(8, 8, 20), outline=col, width=3)
    d.text((48, 1048), name.upper(), font=FONT[26], fill=col)
    for i, line in enumerate(textwrap.wrap(text, 40)[:5]):
        d.text((48, 1086 + i * 30), line, font=FONT[26], fill=(255, 255, 255))


# ---------- speech ----------
def cache_path(spk, text):
    v = VOICES[spk]
    key = f"{v['voice']}|{v['rate']}|{v['pitch']}|{text}".encode("utf-8")
    return os.path.join(CACHE, hashlib.md5(key).hexdigest() + ".mp3")


async def ensure_speech(spk, text):
    path = cache_path(spk, text)
    if not os.path.exists(path):
        v = VOICES[spk]
        await edge_tts.Communicate(text, v["voice"], rate=v["rate"], pitch=v["pitch"]).save(path)
    return path


def decode(path):
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, dtype=np.float32).copy()
    peak = float(np.max(np.abs(a))) or 1.0
    return a * (0.9 / peak)


def envelope(a):
    """Loudness per video frame, 0..1, used to open and close the speaker's mouth."""
    hop = SR // FPS
    n = len(a) // hop + 1
    padded = np.zeros(n * hop, np.float32)
    padded[:len(a)] = a
    rms = np.sqrt((padded.reshape(n, hop) ** 2).mean(axis=1))
    rms = rms / max(1e-6, float(np.percentile(rms, 98)))
    return np.clip(rms, 0, 1)


# ---------- music and sound effects ----------
MOODS = {
    "dramatic": dict(chords=[(57, "m"), (53, "M"), (48, "M"), (55, "M")], bar=2.0, bpm=0, vol=0.10),
    "comedy": dict(chords=[(60, "M"), (65, "M"), (67, "M"), (60, "M")], bar=1.0, bpm=120, arp=True, vol=0.09),
    "triumph": dict(chords=[(60, "M"), (67, "M"), (65, "M"), (60, "M")], bar=1.0, bpm=110, kick=True, vol=0.10),
    "sad": dict(chords=[(57, "m"), (50, "m"), (53, "M"), (52, "M")], bar=2.5, bpm=0, vol=0.09),
    "calm": dict(chords=[(62, "m"), (55, "M"), (58, "M"), (62, "m")], bar=2.0, bpm=0, vol=0.07),
    "mystery": dict(chords=[(50, "m"), (51, "M"), (50, "m"), (46, "M")], bar=1.5, bpm=90, arp=True, vol=0.08),
}


def midi_hz(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def chord_notes(root, q):
    return [root, root + (3 if q == "m" else 4), root + 7]


def add(buf, start, sig):
    end = min(len(buf), start + len(sig))
    if end > start:
        buf[start:end] += sig[:end - start].astype(np.float32)


def make_music(mood, dur):
    cfg = MOODS[mood]
    buf = np.zeros(int(dur * SR) + 1, np.float32)
    pos, ci = 0.0, 0
    while pos < dur - 1e-6:
        root, q = cfg["chords"][ci % len(cfg["chords"])]
        seg = min(cfg["bar"], dur - pos)
        m = int(seg * SR)
        tt = np.arange(m) / SR
        env = np.minimum(1, tt / 0.4) * np.minimum(1, (seg - tt) / 0.4)
        pad = np.zeros(m)
        for note in chord_notes(root - 12, q):
            f = midi_hz(note)
            pad += 0.6 * np.sin(2 * np.pi * f * tt) + 0.2 * np.sin(4 * np.pi * f * tt)
        add(buf, int(pos * SR), pad * env * cfg["vol"] / 3)
        if cfg.get("arp"):
            step = 60.0 / cfg["bpm"] / 2
            tp, k = 0.0, 0
            while tp < seg:
                note = chord_notes(root + 12, q)[k % 3]
                pm = int(min(0.25, seg - tp) * SR)
                tn = np.arange(pm) / SR
                pluck = np.sin(2 * np.pi * midi_hz(note) * tn) * np.exp(-tn * 14)
                add(buf, int((pos + tp) * SR), pluck * cfg["vol"] * 0.8)
                tp += step
                k += 1
        if cfg.get("kick"):
            step = 60.0 / cfg["bpm"]
            tp = 0.0
            while tp < seg:
                km = int(0.3 * SR)
                tk = np.arange(km) / SR
                freq = 40 + 110 * np.exp(-tk * 12)
                kick = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-tk * 10)
                add(buf, int((pos + tp) * SR), kick * cfg["vol"] * 1.5)
                tp += step
        pos += seg
        ci += 1
    return buf[:int(dur * SR)]


def make_sfx(name):
    rng = np.random.default_rng(5)
    if name == "boing":
        d_ = 0.6
        t = np.arange(int(d_ * SR)) / SR
        f = 220 + 800 * t / d_
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 5)
    elif name == "ding":
        d_ = 1.2
        t = np.arange(int(d_ * SR)) / SR
        s = (np.sin(2 * np.pi * 1320 * t) + 0.4 * np.sin(2 * np.pi * 2640 * t)) * np.exp(-t * 4)
    elif name == "trombone":
        d_ = 1.6
        t = np.arange(int(d_ * SR)) / SR
        f = (415 - 200 * t / d_) * (1 + 0.01 * np.sin(2 * np.pi * 5 * t))
        ph = 2 * np.pi * np.cumsum(f) / SR
        wave_ = sum(np.sin(k * ph) / k for k in range(1, 9))
        s = wave_ * np.minimum(1, t / 0.08) * np.minimum(1, (d_ - t) / 0.3)
    elif name == "sting":
        d_ = 1.0
        t = np.arange(int(d_ * SR)) / SR
        s = sum(np.sin(2 * np.pi * midi_hz(n) * t) for n in (60, 64, 67)) * np.exp(-t * 3)
        s = s + rng.standard_normal(len(t)) * np.exp(-t * 20) * 0.5
    elif name == "cheer":
        d_ = 2.5
        t = np.arange(int(d_ * SR)) / SR
        noise = rng.standard_normal(len(t))
        lp = np.convolve(noise, np.ones(8) / 8, mode="same")
        s = lp * np.minimum(1, t / 0.4) * np.minimum(1, (d_ - t) / 0.6) * 1.5
    elif name == "flash":
        d_ = 0.25
        t = np.arange(int(d_ * SR)) / SR
        s = rng.standard_normal(len(t)) * np.exp(-t * 30)
    elif name == "piano":
        d_ = 2.5
        t = np.arange(int(d_ * SR)) / SR
        s = sum(np.sin(2 * np.pi * 523.25 * k * t) / k for k in range(1, 4)) * np.exp(-t * 1.8)
    else:
        raise ValueError(name)
    return (s * 0.5).astype(np.float32)


# ---------- episode script: shots, dialogue, staging ----------
def A(id_, x, y, s=1.0, expr="neutral", ph=0.0, **kw):
    return dict(id=id_, x=x, y=y, s=s, expr=expr, ph=ph, **kw)


def P(kind, x, y, s=1.0, **kw):
    return dict(kind=kind, x=x, y=y, s=s, kw=kw)


SHOTS = [
    dict(title=[("THE RICH LION WHO UNDERESTIMATED HIS DAUGHTER", 44),
                ("Episode 1: The Billionaire's Favourite Child", 30)],
         bg="night", mood="dramatic", dur=5.0, sfx=[("sting", 0.2)]),
    dict(bg="mansion", mood="dramatic",
         lines=[("narr", "Ek sheher mein Raja Sher Singh naam ka ek bahut ameer sher rehta tha.")]),
    dict(bg="hall", mood="dramatic", props=[P("throne", 360, 820)],
         actors=[A("raja", 360, 470, 1.0, "smug")],
         lines=[("narr", "Uske paas duniya ki sabse mehengi gaadiyan aur karodon ki daulat thi.")]),
    dict(bg="hall", mood="dramatic", actors=[A("raja", 360, 520, 1.4, "smug")],
         lines=[("narr", "Lekin uski ek buri aadat thi. Woh apne bete Rocky ko bahut pyaar karta tha...")]),
    dict(bg="hall", mood="sad", actors=[A("raja", 280, 470, 1.0, "smug"), A("rani", 580, 620, 0.55, "sad")],
         lines=[("narr", "...lekin apni beti Rani ko hamesha kam samajhta tha.")]),
    dict(bg="hall", mood="comedy", actors=[A("raja", 360, 500, 1.1, "proud")],
         lines=[("raja", "Aaj main tum dono ko duniya ka sabse khaas tohfa dene wala hoon!")]),
    dict(bg="hall", mood="comedy", actors=[A("rocky", 360, 500, 1.0, "happy", shades=True)],
         lines=[("rocky", "Papa! Mujhe pata hai mere liye Lamborghini hogi!")], sfx=[("boing", 0.2)]),
    dict(bg="hall", mood="calm", actors=[A("rani", 360, 520, 1.0, "sad")],
         lines=[("rani", "Papa, mere liye kya hai?")]),
    dict(bg="hall", mood="comedy", actors=[A("raja", 300, 500, 1.0, "smug"), A("rani", 580, 600, 0.6, "sad")],
         lines=[("raja", "Tum bhi dekh lena. Pehle mere sherzaade ka tohfa!")]),
    dict(bg="hall", mood="dramatic", actors=[A("raja", 150, 520, 0.9, "smug"), A("tiger", 440, 560, 1.0, "happy")],
         lines=[("raja", "Rocky! Yeh duniya ka sabse rare aur powerful white tiger hai. Iski keemat 50 crore rupaye hai!")],
         sfx=[("sting", 0.0)]),
    dict(bg="hall", mood="comedy", actors=[A("rocky", 220, 500, 1.0, "happy", shades=True), A("tiger", 500, 560, 1.0, "happy")],
         lines=[("rocky", "HAHAHA! Dekha Rani? Papa jaante hain asli waaris kaun hai!")], sfx=[("flash", 1.2)]),
    dict(bg="hall", mood="triumph", actors=[A("raja", 230, 500, 1.0, "proud"), A("rocky", 500, 500, 0.9, "happy", shades=True)],
         lines=[("raja", "Mera beta ek din duniya par raaj karega. Isse behtar pet uske liye ho hi nahi sakta!")]),
    dict(bg="hall", mood="calm", props=[P("box", 360, 840)], actors=[A("rani", 360, 500, 1.0, "neutral")],
         lines=[("rani", "Papa... yeh mere liye hai?")]),
    dict(bg="hall", mood="comedy", props=[P("box", 360, 840)],
         actors=[A("raja", 150, 500, 0.9, "smug"), A("chintu", 360, 700, 1.5, "happy")],
         lines=[("raja", "Haan! Tumhare liye bhi ek tohfa hai. Is chuhe ki keemat poore 10 rupaye hai!")],
         sfx=[("trombone", 2.5)]),
    dict(bg="hall", mood="comedy",
         actors=[A("rocky", 200, 500, 1.0, "happy", shades=True), A("rani", 540, 520, 0.8, "sad"),
                 A("chintu", 540, 720, 0.8, "happy")],
         lines=[("rocky", "HAHAHAHA! Rani ko 10 rupaye ka chuha mila! Iska naam gareebi rakhna!")]),
    dict(bg="hall", mood="dramatic", actors=[A("raja", 360, 470, 1.1, "angry"), A("rani", 580, 600, 0.6, "sad")],
         lines=[("raja", "Ladkiyon ko itne mehange pets ki kya zaroorat? Tum isi se khush raho.")]),
    dict(bg="hall", mood="calm", actors=[A("rani", 330, 470, 1.0, "shock"), A("chintu", 360, 720, 1.2, "happy")],
         lines=[("rani", "Theek hai Papa. Main ise hi rakhungi.")], sfx=[("ding", 1.8)]),
    dict(bg="stadium", banner="ROYAL PET CHAMPIONSHIP", mood="dramatic", props=[P("podium", 360, 760)],
         crowd=dict(y=880, cheer=False), actors=[A("raja", 360, 380, 0.9, "proud")],
         lines=[("raja", "Kal sheher mein Royal Pet Championship hoga! Jiska pet sabse powerful hoga, woh jeetega 100 crore rupaye!")]),
    dict(bg="stadium", mood="comedy", crowd=dict(y=880, cheer=False),
         actors=[A("rocky", 250, 500, 1.0, "happy", shades=True), A("tiger", 480, 560, 0.9, "happy")],
         lines=[("rocky", "Papa! Yeh toh already meri jeb mein hain. Mera tiger sabko hara dega!")]),
    dict(bg="stadium", mood="triumph", crowd=dict(y=880, cheer=False), actors=[A("raja", 360, 470, 1.1, "proud")],
         lines=[("raja", "Mujhe apne bete par poora bharosa hai!")]),
    dict(bg="stadium", mood="dramatic", crowd=dict(y=880, cheer=False),
         actors=[A("rani", 280, 520, 1.0, "calm"), A("rocky", 520, 500, 1.0, "smug", shades=True)],
         lines=[("rani", "Papa, main bhi competition mein participate karungi."),
                ("rocky", "Tumhara chuha competition mein kya karega? Trophy kha jayega?")]),
    dict(bg="night", mood="mystery", props=[P("box", 560, 880, 0.9)],
         actors=[A("rani", 330, 520, 1.0, "happy"), A("chintu", 300, 740, 0.9, "happy")],
         lines=[("rani", "Toh tum sirf ek chhote chuhe nahi ho... tum toh genius ho!")], sfx=[("ding", 2.0)]),
    dict(bg="night", mood="comedy", props=[P("block", 500, 900, 1.0, w=260, h=60)],
         actors=[A("rocky", 520, 500, 0.9, "happy", shades=True), A("tiger", 220, 560, 1.0, "happy")],
         lines=[("rocky", "Mera tiger itna powerful hai ki bina training ke bhi jeet jayega!")]),
    dict(bg="stadium", banner="CHALLENGE 1: STRENGTH", mood="comedy", sfx=[("cheer", 0.3)],
         props=[P("block", 470, 940, 1.0, w=300, h=160), P("block", 200, 1000, 1.0, w=90, h=40)],
         actors=[A("tiger", 330, 520, 1.0, "happy"), A("chintu", 200, 900, 0.5, "sad"),
                 A("rocky", 580, 440, 0.6, "happy", shades=True)],
         lines=[("anno", "Challenge 1, Strength!"),
                ("rocky", "HAHAHA! Papa, dekha? Winner toh main hi hoon!")]),
    dict(bg="stadium", banner="CHALLENGE 2: INTELLIGENCE", mood="comedy", sfx=[("ding", 2.8)],
         props=[P("maze", 360, 880, 1.0)],
         actors=[A("tiger", 200, 540, 0.9, "sad"), A("chintu", 540, 760, 0.7, "happy")],
         lines=[("anno", "UNBELIEVABLE! 10 rupaye ka chuha pehle number par!")]),
    dict(bg="stadium", banner="CHALLENGE 3: RESCUE", mood="triumph", sfx=[("cheer", 0.5), ("sting", 0.0)],
         props=[P("tunnel", 360, 860, 1.0, w=420), P("key", 580, 640, 1.0)],
         actors=[A("tiger", 200, 520, 0.9, "sad"), A("chintu", 340, 740, 0.6, "happy")],
         lines=[("anno", "THE WINNER IS... RANI AND HER LITTLE RAT!")]),
    dict(bg="stadium", mood="dramatic", crowd=dict(y=880, cheer=True), sfx=[("cheer", 0.0)],
         actors=[A("rocky", 230, 500, 1.0, "shock"), A("raja", 500, 500, 1.0, "angry")],
         lines=[("rocky", "WHAT?! Yeh kaise ho sakta hai?!"),
                ("raja", "Yeh... yeh sab galat hai! Mera beta ka tiger sabse powerful hai!")]),
    dict(bg="stadium", mood="calm", crowd=dict(y=880, cheer=False), sfx=[("piano", 0.0)],
         actors=[A("rani", 360, 520, 1.0, "calm")],
         lines=[("rani", "Papa, aapne mujhe 10 rupaye ka chuha diya tha. Lekin aap bhool gaye ki kisi ki keemat uske dikhne se nahi hoti.")]),
    dict(bg="stadium", mood="calm", crowd=dict(y=880, cheer=False),
         actors=[A("rani", 360, 520, 1.0, "proud")],
         lines=[("rani", "Aapne bhai ko sab kuch diya, kyunki aapko laga woh ladka hai. Mujhe kuch nahi diya, kyunki aapko laga main ladki hoon. Lekin aaj maine prove kar diya ki talent ka gender nahi hota!")]),
    dict(bg="stadium", mood="triumph", dur=4.5, crowd=dict(y=880, cheer=True), sfx=[("cheer", 0.0)],
         props=[P("trophy", 360, 330, 1.4)], actors=[A("rani", 360, 520, 1.0, "happy")]),
    dict(bg="hall", mood="sad", actors=[A("raja", 220, 500, 1.0, "sad"), A("rani", 500, 520, 1.0, "neutral")],
         lines=[("raja", "Rani... mujhe maaf kar do. Main bahut galat tha. Aaj tumne mujhe sikha diya ki asli taakat dimaag aur mehnat mein hoti hai.")]),
    dict(bg="hall", mood="calm", actors=[A("rani", 360, 520, 1.0, "happy")],
         lines=[("rani", "Papa, mujhe kabhi mehenga gift nahi chahiye tha. Bas aapka bharosa chahiye tha.")]),
    dict(bg="hall", mood="comedy", actors=[A("rocky", 250, 500, 1.0, "happy", shades=True), A("rani", 480, 520, 1.0, "happy")],
         lines=[("rocky", "Rani... mujhe bhi apna chuha train karna sikha do!")]),
    dict(bg="stadium", mood="triumph", crowd=dict(y=880, cheer=True), sfx=[("cheer", 1.0)],
         props=[P("trophy", 520, 330, 1.0)],
         actors=[A("raja", 260, 520, 1.0, "happy"), A("rani", 480, 520, 1.0, "happy"),
                 A("chintu", 580, 720, 0.6, "happy")],
         lines=[("narr", "Jise duniya ne sabse kamzor samjha tha, aaj usi ne sabko hara diya. Kyunki asli winner woh nahi hota jiske paas sabse mehengi cheez ho, balki woh hota hai jo apni mehnat se sab kuch haasil kare!")]),
    dict(title=[("THE END", 60), ("Episode 2 coming soon", 34)], bg="night", mood="calm", dur=5.0),
]


# ---------- timeline, frame rendering and muxing ----------
def mouth_at(shot, aid, t):
    for L in shot["lines"]:
        if L["spk"] == aid and L["s"] <= t < L["s"] + L["dur"]:
            i = min(int((t - L["s"]) * FPS), len(L["env"]) - 1)
            return float(min(1.0, L["env"][i] * 1.1))
    return 0.0


def render_frame(shot, bg, t):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    if shot.get("title"):
        draw_title(d, shot["title"])
        return img
    if shot.get("banner"):
        draw_banner(d, shot["banner"])
    for p in shot.get("props", []):
        PROPS[p["kind"]](d, p["x"], p["y"], p["s"], **p["kw"])
    if shot.get("crowd"):
        draw_crowd(d, shot["crowd"]["y"], shot["crowd"]["cheer"], t)
    for a in shot.get("actors", []):
        ACTOR_FN[a["id"]](d, a, t, mouth_at(shot, a["id"], t))
    for L in shot["lines"]:
        if L["s"] <= t < L["s"] + L["dur"] + 0.15:
            draw_subtitle(d, L["spk"], L["text"])
            break
    return img


def build_timeline():
    async def fetch_all():
        for shot in SHOTS:
            for spk, text in shot.get("lines", []):
                await ensure_speech(spk, text)
    asyncio.run(fetch_all())

    cursor = 0.0
    for shot in SHOTS:
        shot["start"] = cursor
        local, lines = 0.4, []
        for spk, text in shot.get("lines", []):
            audio = decode(cache_path(spk, text))
            dur = len(audio) / SR
            lines.append(dict(spk=spk, text=text, s=local, dur=dur, audio=audio, env=envelope(audio)))
            local += dur + 0.3
        shot["lines"] = lines
        shot["len"] = max(shot.get("dur", 0), 3.0, local + 0.6)
        cursor += shot["len"]
    return cursor


def build_audio(total):
    n = int(total * SR) + SR
    music = np.zeros(n, np.float32)
    dialogue = np.zeros(n, np.float32)
    effects = np.zeros(n, np.float32)
    for shot in SHOTS:
        s0 = int(shot["start"] * SR)
        m = make_music(shot.get("mood", "calm"), shot["len"])
        for L in shot["lines"]:
            a0 = int(L["s"] * SR)
            m[a0:a0 + len(L["audio"])] *= 0.45  # duck the music under speech
            add(dialogue, s0 + a0, L["audio"])
        add(music, s0, m)
        for name, t in shot.get("sfx", []):
            add(effects, s0 + int(t * SR), make_sfx(name))
    mix = music + dialogue + effects * 0.8
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.97:
        mix *= 0.97 / peak
    return mix[:int(total * SR)]


def write_wav(path, audio):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def render_video(total, path):
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    bgs, clock = {}, 0.0
    for shot in SHOTS:
        theme = shot.get("bg", "night")
        if theme not in bgs:
            bgs[theme] = make_bg(theme)
        for i in range(int(round(shot["len"] * FPS))):
            t = i / FPS
            img = render_frame(shot, bgs[theme], t)
            g = clock + t  # global time, used for the fade in and fade out
            fade = min(1.0, g / 0.6, max(0.0, (total - g) / 1.0))
            if fade < 1.0:
                img = Image.blend(Image.new("RGB", (W, H)), img, max(0.0, fade))
            proc.stdin.write(img.tobytes())
        clock += shot["len"]
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg video encode failed")


def main():
    total = build_timeline()
    print(f"Timeline: {len(SHOTS)} shots, {total:.1f} seconds", flush=True)
    audio = build_audio(total)
    wav_path = os.path.join(CACHE, "episode-01-audio.wav")
    write_wav(wav_path, audio)
    print("Audio mixed", flush=True)
    video_only = os.path.join(CACHE, "episode-01-video.mp4")
    render_video(total, video_only)
    print("Video rendered", flush=True)
    final = os.path.join(OUT, "episode-01.mp4")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", video_only, "-i", wav_path,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", final], check=True)
    print(f"Done: {final}", flush=True)


if __name__ == "__main__":
    main()
